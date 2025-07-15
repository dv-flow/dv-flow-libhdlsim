
import shlex
from typing import List


def merge_tokenize(input : List[str]) -> List[str]:
    merged = []
    for elem in input:
        merged.extend(shlex.split(elem))
    return merged

