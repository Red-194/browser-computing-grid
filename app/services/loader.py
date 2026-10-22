from importlib import import_module


def _get_class(workload: str, component: str):

    module = import_module(
        f"app.services.{component}s.{workload}"
    )

    workload_name = "SAT" if workload == "sat" else "".join(
        word.capitalize() for word in workload.split("_")
    )
    class_name = workload_name + component.capitalize()

    return getattr(module, class_name)


def get_splitter(workload: str):
    return _get_class(workload, "splitter")()


def get_aggregator(workload: str, config):
    return _get_class(workload, "aggregator")(config)
