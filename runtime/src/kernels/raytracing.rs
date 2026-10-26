use serde::{Deserialize, Serialize};

const EPSILON: f64 = 1e-4;

type Vec3 = [f64; 3];

#[derive(Deserialize)]
pub struct RayCamera {
    pub position: Vec3,
    pub look_at: Vec3,
    pub vertical_fov_degrees: f64,
}

#[derive(Deserialize)]
pub struct RaySphere {
    pub center: Vec3,
    pub radius: f64,
    pub color: Vec3,
    pub reflectivity: f64,
}

#[derive(Deserialize)]
pub struct RayLight {
    pub position: Vec3,
    pub color: Vec3,
    pub intensity: f64,
}

#[derive(Deserialize)]
pub struct RayScene {
    pub camera: RayCamera,
    pub spheres: Vec<RaySphere>,
    pub lights: Vec<RayLight>,
    pub background: Vec3,
}

#[derive(Deserialize)]
pub struct RayTracingInput {
    pub width: u32,
    pub height: u32,
    pub tile_size: u32,
    pub row_block: u32,
    pub col_block: u32,
    pub samples_per_pixel: u32,
    pub max_bounces: u32,
    pub scene: RayScene,
}

#[derive(Default, Serialize, Deserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub struct RayWorkStats {
    pub primary_rays: u64,
    pub total_rays: u64,
    pub sphere_tests: u64,
    pub shadow_rays: u64,
    pub reflection_rays: u64,
    pub light_samples: u64,
}

#[derive(Serialize, Deserialize)]
pub struct RayTracingOutput {
    pub row_block: u32,
    pub col_block: u32,
    pub tile_width: u32,
    pub tile_height: u32,
    pub pixel_buffer: Vec<u8>,
    pub work_stats: RayWorkStats,
}

#[derive(Clone, Copy)]
struct Ray {
    origin: Vec3,
    direction: Vec3,
}

#[derive(Clone, Copy)]
struct Hit {
    sphere_index: usize,
    point: Vec3,
    normal: Vec3,
}

pub fn run(input: RayTracingInput) -> RayTracingOutput {
    let start_x = input.col_block.saturating_mul(input.tile_size);
    let start_y = input.row_block.saturating_mul(input.tile_size);
    let tile_width = input.tile_size.min(input.width.saturating_sub(start_x));
    let tile_height = input.tile_size.min(input.height.saturating_sub(start_y));
    let mut output = RayTracingOutput {
        row_block: input.row_block,
        col_block: input.col_block,
        tile_width,
        tile_height,
        pixel_buffer: Vec::with_capacity(tile_width as usize * tile_height as usize * 3),
        work_stats: RayWorkStats::default(),
    };

    if input.width == 0
        || input.height == 0
        || input.tile_size == 0
        || input.samples_per_pixel == 0
        || tile_width == 0
        || tile_height == 0
    {
        return output;
    }

    let camera = &input.scene.camera;
    let forward = normalize(sub(camera.look_at, camera.position));
    let mut right = normalize(cross(forward, [0.0, 1.0, 0.0]));
    if dot(right, right) <= 1e-15 {
        right = [1.0, 0.0, 0.0];
    }
    let up = normalize(cross(right, forward));
    let half_height = (camera.vertical_fov_degrees.to_radians() * 0.5).tan();
    let aspect = input.width as f64 / input.height as f64;

    for local_y in 0..tile_height {
        for local_x in 0..tile_width {
            let global_x = start_x + local_x;
            let global_y = start_y + local_y;
            let mut pixel = [0.0; 3];
            for sample in 0..input.samples_per_pixel {
                let seed = sample_seed(global_x, global_y, sample);
                let jitter_x = unit_float(splitmix64(seed));
                let jitter_y = unit_float(splitmix64(seed.wrapping_add(1)));
                let screen_x =
                    (2.0 * (global_x as f64 + jitter_x) / input.width as f64 - 1.0)
                        * aspect
                        * half_height;
                let screen_y =
                    (1.0 - 2.0 * (global_y as f64 + jitter_y) / input.height as f64)
                        * half_height;
                let direction = normalize(add(
                    forward,
                    add(scale(right, screen_x), scale(up, screen_y)),
                ));
                output.work_stats.primary_rays += 1;
                let color = trace(
                    Ray {
                        origin: camera.position,
                        direction,
                    },
                    &input.scene,
                    0,
                    input.max_bounces,
                    &mut output.work_stats,
                );
                pixel = add(pixel, color);
            }
            pixel = scale(pixel, 1.0 / input.samples_per_pixel as f64);
            output.pixel_buffer.extend_from_slice(&[
                to_byte(pixel[0]),
                to_byte(pixel[1]),
                to_byte(pixel[2]),
            ]);
        }
    }

    output
}

fn trace(ray: Ray, scene: &RayScene, depth: u32, max_bounces: u32, work: &mut RayWorkStats) -> Vec3 {
    work.total_rays += 1;
    let Some(hit) = nearest_hit(ray, scene, f64::INFINITY, work) else {
        return scene.background;
    };
    let sphere = &scene.spheres[hit.sphere_index];
    let mut local = scale(multiply(sphere.color, scene.background), 0.055);

    for light in &scene.lights {
        let to_light = sub(light.position, hit.point);
        let light_distance_squared = dot(to_light, to_light);
        if light_distance_squared <= EPSILON * EPSILON {
            continue;
        }
        let light_distance = light_distance_squared.sqrt();
        let light_direction = scale(to_light, 1.0 / light_distance);
        let diffuse = dot(hit.normal, light_direction).max(0.0);
        if diffuse <= 0.0 {
            continue;
        }

        work.light_samples += 1;
        work.shadow_rays += 1;
        work.total_rays += 1;
        let shadow = Ray {
            origin: add(hit.point, scale(hit.normal, EPSILON)),
            direction: light_direction,
        };
        if !occluded(shadow, scene, hit.sphere_index, light_distance - EPSILON, work) {
            let attenuation = light.intensity / (light_distance_squared + 1.0);
            let brightness = diffuse * attenuation;
            local = add(local, scale(multiply(sphere.color, light.color), brightness));
        }
    }

    let reflectivity = sphere.reflectivity.clamp(0.0, 1.0);
    if reflectivity > 0.0 && depth < max_bounces {
        work.reflection_rays += 1;
        let reflected = normalize(sub(
            ray.direction,
            scale(hit.normal, 2.0 * dot(ray.direction, hit.normal)),
        ));
        let reflection = trace(
            Ray {
                origin: add(hit.point, scale(hit.normal, EPSILON)),
                direction: reflected,
            },
            scene,
            depth + 1,
            max_bounces,
            work,
        );
        add(scale(local, 1.0 - reflectivity), scale(reflection, reflectivity))
    } else {
        local
    }
}

fn nearest_hit(ray: Ray, scene: &RayScene, maximum: f64, work: &mut RayWorkStats) -> Option<Hit> {
    let mut closest = maximum;
    let mut nearest = None;
    for (sphere_index, sphere) in scene.spheres.iter().enumerate() {
        work.sphere_tests += 1;
        if let Some(distance) = intersect_sphere(ray, sphere, closest) {
            closest = distance;
            let point = add(ray.origin, scale(ray.direction, distance));
            nearest = Some(Hit {
                sphere_index,
                point,
                normal: normalize(sub(point, sphere.center)),
            });
        }
    }
    nearest
}

fn occluded(
    ray: Ray,
    scene: &RayScene,
    ignored_sphere: usize,
    maximum: f64,
    work: &mut RayWorkStats,
) -> bool {
    for (index, sphere) in scene.spheres.iter().enumerate() {
        if index == ignored_sphere {
            continue;
        }
        work.sphere_tests += 1;
        if intersect_sphere(ray, sphere, maximum).is_some() {
            return true;
        }
    }
    false
}

fn intersect_sphere(ray: Ray, sphere: &RaySphere, maximum: f64) -> Option<f64> {
    let offset = sub(ray.origin, sphere.center);
    let half_b = dot(offset, ray.direction);
    let c = dot(offset, offset) - sphere.radius * sphere.radius;
    let discriminant = half_b * half_b - c;
    if discriminant < 0.0 {
        return None;
    }
    let root = discriminant.sqrt();
    let mut distance = -half_b - root;
    if distance <= EPSILON || distance >= maximum {
        distance = -half_b + root;
        if distance <= EPSILON || distance >= maximum {
            return None;
        }
    }
    Some(distance)
}

fn sample_seed(x: u32, y: u32, sample: u32) -> u64 {
    (x as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15)
        ^ (y as u64).wrapping_mul(0xbf58_476d_1ce4_e5b9)
        ^ (sample as u64).wrapping_mul(0x94d0_49bb_1331_11eb)
}

fn splitmix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

fn unit_float(value: u64) -> f64 {
    ((value >> 11) as f64) * (1.0 / ((1u64 << 53) as f64))
}

fn to_byte(value: f64) -> u8 {
    (value.clamp(0.0, 1.0).powf(1.0 / 2.2) * 255.0 + 0.5) as u8
}

fn add(a: Vec3, b: Vec3) -> Vec3 {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}

fn sub(a: Vec3, b: Vec3) -> Vec3 {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

fn scale(v: Vec3, amount: f64) -> Vec3 {
    [v[0] * amount, v[1] * amount, v[2] * amount]
}

fn multiply(a: Vec3, b: Vec3) -> Vec3 {
    [a[0] * b[0], a[1] * b[1], a[2] * b[2]]
}

fn dot(a: Vec3, b: Vec3) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

fn cross(a: Vec3, b: Vec3) -> Vec3 {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}

fn normalize(v: Vec3) -> Vec3 {
    let length = dot(v, v).sqrt();
    if length <= 1e-15 {
        [0.0, 0.0, 0.0]
    } else {
        scale(v, 1.0 / length)
    }
}
