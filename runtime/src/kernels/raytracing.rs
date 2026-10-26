use serde::{Deserialize, Serialize};

const EPSILON: f64 = 1e-4;
type Vec3 = [f64; 3];

#[derive(Deserialize)]
pub struct RayCamera { pub position: Vec3, pub look_at: Vec3, pub vertical_fov_degrees: f64 }

#[derive(Deserialize)]
pub struct RaySphere {
    pub center: Vec3, pub radius: f64, pub color: Vec3, pub reflectivity: f64,
    #[serde(default)] pub transparency: f64,
    #[serde(default = "default_refractive_index")] pub refractive_index: f64,
}

#[derive(Deserialize)]
pub struct RayBox {
    pub minimum: Vec3, pub maximum: Vec3, pub color: Vec3, pub reflectivity: f64,
    #[serde(default)] pub transparency: f64,
    #[serde(default = "default_refractive_index")] pub refractive_index: f64,
}

#[derive(Deserialize)]
pub struct RayPlane {
    pub point: Vec3, pub normal: Vec3, pub color: Vec3, pub reflectivity: f64,
    #[serde(default)] pub transparency: f64,
    #[serde(default = "default_refractive_index")] pub refractive_index: f64,
}

#[derive(Deserialize)]
pub struct RayLight { pub position: Vec3, pub color: Vec3, pub intensity: f64 }

#[derive(Deserialize)]
pub struct RayScene {
    pub camera: RayCamera,
    pub spheres: Vec<RaySphere>,
    #[serde(default)] pub boxes: Vec<RayBox>,
    #[serde(default)] pub planes: Vec<RayPlane>,
    pub lights: Vec<RayLight>,
    pub background: Vec3,
}

#[derive(Deserialize)]
pub struct RayTracingInput {
    pub width: u32, pub height: u32, pub tile_size: u32,
    pub row_block: u32, pub col_block: u32,
    pub samples_per_pixel: u32, pub max_bounces: u32, pub scene: RayScene,
}

#[derive(Default, Serialize, Deserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub struct RayWorkStats {
    pub primary_rays: u64, pub total_rays: u64,
    pub sphere_tests: u64, pub box_tests: u64, pub plane_tests: u64,
    pub shadow_rays: u64, pub reflection_rays: u64, pub refraction_rays: u64,
    pub light_samples: u64,
}

#[derive(Serialize, Deserialize)]
pub struct RayTracingOutput {
    pub row_block: u32, pub col_block: u32,
    pub tile_width: u32, pub tile_height: u32,
    pub pixel_buffer: Vec<u8>, pub work_stats: RayWorkStats,
}

#[derive(Clone, Copy)]
struct Ray { origin: Vec3, direction: Vec3 }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum SurfaceId { Sphere(usize), Box(usize), Plane(usize) }

#[derive(Clone, Copy)]
struct Hit {
    surface: SurfaceId, point: Vec3, normal: Vec3, front_face: bool,
    color: Vec3, reflectivity: f64, transparency: f64, refractive_index: f64,
}

impl Hit {
    fn new(ray: Ray, surface: SurfaceId, point: Vec3, outward: Vec3, color: Vec3,
           reflectivity: f64, transparency: f64, refractive_index: f64) -> Self {
        let front_face = dot(ray.direction, outward) < 0.0;
        Self {
            surface, point,
            normal: if front_face { outward } else { scale(outward, -1.0) },
            front_face, color, reflectivity: reflectivity.clamp(0.0, 1.0),
            transparency: transparency.clamp(0.0, 1.0),
            refractive_index: refractive_index.max(1.0),
        }
    }
}

pub fn run(input: RayTracingInput) -> RayTracingOutput {
    let start_x = input.col_block.saturating_mul(input.tile_size);
    let start_y = input.row_block.saturating_mul(input.tile_size);
    let tile_width = input.tile_size.min(input.width.saturating_sub(start_x));
    let tile_height = input.tile_size.min(input.height.saturating_sub(start_y));
    let mut output = RayTracingOutput {
        row_block: input.row_block, col_block: input.col_block, tile_width, tile_height,
        pixel_buffer: Vec::with_capacity(tile_width as usize * tile_height as usize * 3),
        work_stats: RayWorkStats::default(),
    };
    if input.width == 0 || input.height == 0 || input.tile_size == 0
        || input.samples_per_pixel == 0 || tile_width == 0 || tile_height == 0 {
        return output;
    }

    let camera = &input.scene.camera;
    let forward = normalize(sub(camera.look_at, camera.position));
    let mut right = normalize(cross(forward, [0.0, 1.0, 0.0]));
    if dot(right, right) <= 1e-15 { right = [1.0, 0.0, 0.0]; }
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
                let screen_x = (2.0 * (global_x as f64 + jitter_x) / input.width as f64 - 1.0)
                    * aspect * half_height;
                let screen_y = (1.0 - 2.0 * (global_y as f64 + jitter_y) / input.height as f64)
                    * half_height;
                let direction = normalize(add(forward,
                    add(scale(right, screen_x), scale(up, screen_y))));
                output.work_stats.primary_rays += 1;
                let color = trace(Ray { origin: camera.position, direction }, &input.scene,
                    0, input.max_bounces, &mut output.work_stats);
                pixel = add(pixel, color);
            }
            pixel = scale(pixel, 1.0 / input.samples_per_pixel as f64);
            output.pixel_buffer.extend_from_slice(&[
                to_byte(pixel[0]), to_byte(pixel[1]), to_byte(pixel[2]),
            ]);
        }
    }
    output
}

fn trace(ray: Ray, scene: &RayScene, depth: u32, max_bounces: u32,
         work: &mut RayWorkStats) -> Vec3 {
    work.total_rays += 1;
    let Some(hit) = nearest_hit(ray, scene, f64::INFINITY, None, work) else {
        return scene.background;
    };

    let mut local = scale(multiply(hit.color, scene.background), 0.045);
    for light in &scene.lights {
        let to_light = sub(light.position, hit.point);
        let distance_squared = dot(to_light, to_light);
        if distance_squared <= EPSILON * EPSILON { continue; }
        let light_distance = distance_squared.sqrt();
        let light_direction = scale(to_light, 1.0 / light_distance);
        let diffuse = dot(hit.normal, light_direction).max(0.0);
        if diffuse <= 0.0 { continue; }
        work.light_samples += 1;
        work.shadow_rays += 1;
        work.total_rays += 1;
        let visibility = shadow_visibility(
            Ray { origin: add(hit.point, scale(hit.normal, EPSILON * 2.0)), direction: light_direction },
            scene, light_distance - EPSILON, hit.surface, work,
        );
        let brightness = diffuse * light.intensity / (distance_squared + 1.0);
        local = add(local, multiply(scale(multiply(hit.color, light.color), brightness), visibility));
    }

    if depth >= max_bounces { return local; }
    let mut reflection_weight = hit.reflectivity;
    let mut transmission_weight = hit.transparency;
    let refracted = if hit.transparency > 0.0 {
        match refract(ray.direction, hit.normal, hit.front_face, hit.refractive_index) {
            Some(direction) => {
                let fresnel = schlick_fresnel(dot(ray.direction, hit.normal).abs(), hit.refractive_index);
                reflection_weight += hit.transparency * fresnel;
                transmission_weight *= 1.0 - fresnel;
                Some(direction)
            }
            None => { reflection_weight += hit.transparency; transmission_weight = 0.0; None }
        }
    } else { None };

    let local_weight = (1.0 - hit.reflectivity - hit.transparency).max(0.0);
    let total_weight = local_weight + reflection_weight + transmission_weight;
    let normalize_weight = if total_weight > 1.0 { 1.0 / total_weight } else { 1.0 };
    let mut result = scale(local, local_weight * normalize_weight);

    if reflection_weight > 0.0 {
        work.reflection_rays += 1;
        let direction = normalize(sub(ray.direction, scale(hit.normal, 2.0 * dot(ray.direction, hit.normal))));
        let color = trace(Ray { origin: add(hit.point, scale(hit.normal, EPSILON * 2.0)), direction },
            scene, depth + 1, max_bounces, work);
        result = add(result, scale(color, reflection_weight * normalize_weight));
    }
    if transmission_weight > 0.0 {
        if let Some(direction) = refracted {
            work.refraction_rays += 1;
            let color = trace(Ray { origin: sub(hit.point, scale(hit.normal, EPSILON * 2.0)), direction },
                scene, depth + 1, max_bounces, work);
            result = add(result, scale(color, transmission_weight * normalize_weight));
        }
    }
    result
}

fn shadow_visibility(ray: Ray, scene: &RayScene, maximum: f64,
                     origin_surface: SurfaceId, work: &mut RayWorkStats) -> Vec3 {
    let mut origin = ray.origin;
    let mut remaining = maximum;
    let mut visibility = [1.0; 3];
    let max_crossings = scene.spheres.len() * 2 + scene.boxes.len() * 2 + scene.planes.len() + 1;
    for crossing in 0..max_crossings {
        let current = Ray { origin, direction: ray.direction };
        let ignored = if crossing == 0 { Some(origin_surface) } else { None };
        let Some(hit) = nearest_hit(current, scene, remaining, ignored, work) else { return visibility; };
        if hit.transparency <= 0.0 { return [0.0; 3]; }
        visibility = scale(multiply(visibility, hit.color), hit.transparency);
        if visibility.iter().all(|value| *value < 0.01) { return [0.0; 3]; }
        let advance = dot(ray.direction, sub(hit.point, origin)).max(0.0) + EPSILON * 2.0;
        origin = add(origin, scale(ray.direction, advance));
        remaining -= advance;
        if remaining <= EPSILON { return visibility; }
    }
    visibility
}

fn nearest_hit(ray: Ray, scene: &RayScene, maximum: f64, ignored: Option<SurfaceId>,
               work: &mut RayWorkStats) -> Option<Hit> {
    let mut closest = maximum;
    let mut nearest = None;
    for (index, object) in scene.spheres.iter().enumerate() {
        let id = SurfaceId::Sphere(index);
        if ignored == Some(id) { continue; }
        work.sphere_tests += 1;
        if let Some((distance, normal)) = intersect_sphere(ray, object, closest) {
            closest = distance;
            nearest = Some(Hit::new(ray, id, add(ray.origin, scale(ray.direction, distance)), normal,
                object.color, object.reflectivity, object.transparency, object.refractive_index));
        }
    }
    for (index, object) in scene.boxes.iter().enumerate() {
        let id = SurfaceId::Box(index);
        if ignored == Some(id) { continue; }
        work.box_tests += 1;
        if let Some((distance, normal)) = intersect_box(ray, object, closest) {
            closest = distance;
            nearest = Some(Hit::new(ray, id, add(ray.origin, scale(ray.direction, distance)), normal,
                object.color, object.reflectivity, object.transparency, object.refractive_index));
        }
    }
    for (index, object) in scene.planes.iter().enumerate() {
        let id = SurfaceId::Plane(index);
        if ignored == Some(id) { continue; }
        work.plane_tests += 1;
        if let Some((distance, normal)) = intersect_plane(ray, object, closest) {
            closest = distance;
            nearest = Some(Hit::new(ray, id, add(ray.origin, scale(ray.direction, distance)), normal,
                object.color, object.reflectivity, object.transparency, object.refractive_index));
        }
    }
    nearest
}

fn intersect_sphere(ray: Ray, object: &RaySphere, maximum: f64) -> Option<(f64, Vec3)> {
    let offset = sub(ray.origin, object.center);
    let half_b = dot(offset, ray.direction);
    let discriminant = half_b * half_b - (dot(offset, offset) - object.radius * object.radius);
    if discriminant < 0.0 { return None; }
    let root = discriminant.sqrt();
    let mut distance = -half_b - root;
    if distance <= EPSILON || distance >= maximum {
        distance = -half_b + root;
        if distance <= EPSILON || distance >= maximum { return None; }
    }
    let point = add(ray.origin, scale(ray.direction, distance));
    Some((distance, normalize(sub(point, object.center))))
}

fn intersect_box(ray: Ray, object: &RayBox, maximum: f64) -> Option<(f64, Vec3)> {
    let mut near = f64::NEG_INFINITY;
    let mut far = f64::INFINITY;
    let mut near_normal = [0.0; 3];
    let mut far_normal = [0.0; 3];
    for axis in 0..3 {
        let direction = ray.direction[axis];
        if direction.abs() <= 1e-15 {
            if ray.origin[axis] < object.minimum[axis] || ray.origin[axis] > object.maximum[axis] {
                return None;
            }
            continue;
        }
        let mut first = (object.minimum[axis] - ray.origin[axis]) / direction;
        let mut second = (object.maximum[axis] - ray.origin[axis]) / direction;
        let mut first_normal = [0.0; 3];
        let mut second_normal = [0.0; 3];
        first_normal[axis] = -1.0;
        second_normal[axis] = 1.0;
        if first > second {
            std::mem::swap(&mut first, &mut second);
            std::mem::swap(&mut first_normal, &mut second_normal);
        }
        if first > near { near = first; near_normal = first_normal; }
        if second < far { far = second; far_normal = second_normal; }
        if near > far { return None; }
    }
    let (distance, normal) = if near > EPSILON { (near, near_normal) } else { (far, far_normal) };
    if distance <= EPSILON || distance >= maximum { None } else { Some((distance, normal)) }
}

fn intersect_plane(ray: Ray, object: &RayPlane, maximum: f64) -> Option<(f64, Vec3)> {
    let normal = normalize(object.normal);
    let denominator = dot(ray.direction, normal);
    if denominator.abs() <= 1e-15 { return None; }
    let distance = dot(sub(object.point, ray.origin), normal) / denominator;
    if distance <= EPSILON || distance >= maximum { None } else { Some((distance, normal)) }
}

fn refract(direction: Vec3, normal: Vec3, front_face: bool, refractive_index: f64) -> Option<Vec3> {
    let eta = if front_face { 1.0 / refractive_index } else { refractive_index };
    let cosine = (-dot(direction, normal)).clamp(0.0, 1.0);
    let sine_squared = 1.0 - cosine * cosine;
    if eta * eta * sine_squared > 1.0 { return None; }
    let perpendicular = scale(add(direction, scale(normal, cosine)), eta);
    let parallel = scale(normal, -(1.0 - dot(perpendicular, perpendicular)).abs().sqrt());
    Some(normalize(add(perpendicular, parallel)))
}

fn schlick_fresnel(cosine: f64, refractive_index: f64) -> f64 {
    let ratio = (1.0 - refractive_index) / (1.0 + refractive_index);
    let r0 = ratio * ratio;
    r0 + (1.0 - r0) * (1.0 - cosine.clamp(0.0, 1.0)).powi(5)
}

fn default_refractive_index() -> f64 { 1.5 }
fn sample_seed(x: u32, y: u32, sample: u32) -> u64 {
    (x as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15)
        ^ (y as u64).wrapping_mul(0xbf58_476d_1ce4_e5b9)
        ^ (sample as u64).wrapping_mul(0x94d0_49bb_1331_11eb)
}
fn splitmix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    let mut z = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    z ^ (z >> 31)
}
fn unit_float(value: u64) -> f64 { ((value >> 11) as f64) * (1.0 / ((1u64 << 53) as f64)) }
fn to_byte(value: f64) -> u8 { (value.clamp(0.0, 1.0).powf(1.0 / 2.2) * 255.0 + 0.5) as u8 }
fn add(a: Vec3, b: Vec3) -> Vec3 { [a[0] + b[0], a[1] + b[1], a[2] + b[2]] }
fn sub(a: Vec3, b: Vec3) -> Vec3 { [a[0] - b[0], a[1] - b[1], a[2] - b[2]] }
fn scale(v: Vec3, amount: f64) -> Vec3 { [v[0] * amount, v[1] * amount, v[2] * amount] }
fn multiply(a: Vec3, b: Vec3) -> Vec3 { [a[0] * b[0], a[1] * b[1], a[2] * b[2]] }
fn dot(a: Vec3, b: Vec3) -> f64 { a[0] * b[0] + a[1] * b[1] + a[2] * b[2] }
fn cross(a: Vec3, b: Vec3) -> Vec3 {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}
fn normalize(v: Vec3) -> Vec3 {
    let length = dot(v, v).sqrt();
    if length <= 1e-15 { [0.0; 3] } else { scale(v, 1.0 / length) }
}
