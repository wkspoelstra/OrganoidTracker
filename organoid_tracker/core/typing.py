from typing import Union, Tuple, List

MPLColor = Union[
    Tuple[float, float, float],
    Tuple[float, float, float, float],
    str,
    float
]

# Primitive types that can be stored directly in JSON files.
DataType = Union[
    float,
    int,
    str,
    bool,
    List[float],
    List[int],
    List[str],
    List[bool]
]
