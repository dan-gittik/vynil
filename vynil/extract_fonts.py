import pathlib

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ITALIC_SUFFIX = "-italic"


def extract_fonts(variable_font_path: str | pathlib.Path) -> None:
    path = pathlib.Path(variable_font_path)
    if path.is_dir():
        for file in path.iterdir():
            extract_fonts(file)
        return
    font = TTFont(variable_font_path)
    if "fvar" not in font:
        print(f"{path.stem} is not a variable font.")
        return
    fvar = font["fvar"]
    name_table = font["name"]
    for instance in fvar.instances:
        name_id = instance.subfamilyNameID
        instance_name = name_table.getName(name_id, 3, 1, 0x409) or name_table.getName(name_id, 1, 0, 0)
        if instance_name is None:
            continue
        print(f"Extracting {path.stem}/{instance_name}... ", end="")
        coordinates = {axis.axisTag: instance.coordinates.get(axis.axisTag, axis.defaultValue) for axis in fvar.axes}
        instantiated = instantiateVariableFont(font, axisLimits=coordinates, inplace=False)
        basename = path.stem
        if basename.lower().endswith(ITALIC_SUFFIX):
            basename = basename[: -len(ITALIC_SUFFIX)]
        output_path = path.with_name(f"{basename}-{str(instance_name).replace(' ', '')}.ttf")
        instantiated.save(output_path)
        print("done")
