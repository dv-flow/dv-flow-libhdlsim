
import shlex
from typing import List


def merge_tokenize(input : List[str]) -> List[str]:
    merged = []
    if type(input) == str:
        merged.extend(shlex.split(str(input)))
    else:
        for elem in input:
            merged.extend(shlex.split(elem))
    return merged

