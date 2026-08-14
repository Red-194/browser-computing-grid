from importlib import import_module


def get_splitter(workload: str):

    module = import_module(
        f"app.splitters.{workload}"
    )

    class_name = "".join(
        word.capitalize()
        for word in workload.split("_")
    ) + "Splitter"

    splitter_class = getattr(module, class_name)

    return splitter_class()