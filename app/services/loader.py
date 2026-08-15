from importlib import import_module


def _get_class(workload: str, component: str):

    module = import_module(
        f"app.services.{component}s.{workload}"
    )

    class_name = (
        "".join(word.capitalize() for word in workload.split("_"))
        + component.capitalize()
    )

    return getattr(module, class_name)


def get_splitter(workload: str):
    return _get_class(workload, "splitter")()


def get_aggregator(workload: str, config):
    return _get_class(workload, "aggregator")(config)