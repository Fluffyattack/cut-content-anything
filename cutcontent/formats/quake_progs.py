"""Reader for compiled QuakeC game code (``progs.dat``, version 6).

The analysis needs two things from it:

- the string table: QuakeC loads models and sounds by file name
  (``precache_model("progs/ogre.mdl")``), so every asset name the game code can
  load appears as a string here;
- the function names: an entity class in a level (``monster_ogre``) is created by
  calling the QuakeC function with exactly that name. A class without a function
  is removed when the level loads, and a spawn function no level uses may be a
  cut entity type.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

PROGS_VERSION = 6
HEADER_FORMAT = "<15i"
FUNCTION_FORMAT = "<7i8B"
FUNCTION_SIZE = struct.calcsize(FUNCTION_FORMAT)
TYPE_FUNCTION = 6
SAVE_GLOBAL_FLAG = 1 << 15


class ProgsFormatError(ValueError):
    pass


@dataclass
class ProgsFunction:
    name: str
    source_file: str
    is_builtin: bool


@dataclass
class QuakeGameCode:
    version: int
    checksum: int
    strings: list[str]
    functions: list[ProgsFunction]
    referenced_functions: set[str]

    def function_names(self) -> set[str]:
        return {function.name for function in self.functions if not function.is_builtin}

    def functions_only_callable_by_name(self) -> set[str]:
        """Functions no statement of the game code refers to (no call, no assignment
        such as ``self.touch = ...``). The engine can still call them by name, which is
        exactly how it creates entities: these are the spawn functions (or dead code)."""
        return self.function_names() - self.referenced_functions


def read_game_code(data: bytes) -> QuakeGameCode:
    if len(data) < struct.calcsize(HEADER_FORMAT):
        raise ProgsFormatError("game code file is truncated")
    header = struct.unpack_from(HEADER_FORMAT, data, 0)
    version, checksum = header[0], header[1]
    if version != PROGS_VERSION:
        raise ProgsFormatError(f"unsupported game code version {version} (only version 6 is supported)")
    functions_offset, function_count = header[8], header[9]
    strings_offset, strings_size = header[10], header[11]
    if strings_offset < 0 or strings_offset + strings_size > len(data):
        raise ProgsFormatError("string table lies outside the file")
    if functions_offset < 0 or functions_offset + function_count * FUNCTION_SIZE > len(data):
        raise ProgsFormatError("function table lies outside the file")

    string_block = data[strings_offset : strings_offset + strings_size]

    def string_at(offset: int) -> str:
        if not 0 <= offset < len(string_block):
            return ""
        end = string_block.find(b"\0", offset)
        return string_block[offset : end if end >= 0 else len(string_block)].decode("latin-1")

    strings = [part.decode("latin-1") for part in string_block.split(b"\0") if part]
    functions = []
    function_names_by_index = {}
    for index in range(function_count):
        record = struct.unpack_from(FUNCTION_FORMAT, data, functions_offset + index * FUNCTION_SIZE)
        first_statement, name_offset, file_offset = record[0], record[4], record[5]
        name = string_at(name_offset)
        if name:
            functions.append(ProgsFunction(name, string_at(file_offset), first_statement < 0))
            function_names_by_index[index] = name
    referenced = _functions_referenced_by_statements(data, header, function_names_by_index)
    return QuakeGameCode(version, checksum, strings, functions, referenced)


def _functions_referenced_by_statements(data: bytes, header: tuple, function_names_by_index: dict[int, str]) -> set[str]:
    """Finds functions that statements use as a value (calls and assignments).

    Every function has a global variable of type "function" whose value is the
    function's index. Statements refer to globals by offset, so a function is
    referenced when the offset of its global appears as a statement operand.
    """
    statements_offset, statement_count = header[2], header[3]
    definitions_offset, definition_count = header[4], header[5]
    globals_offset, global_count = header[12], header[13]
    if not (0 <= statements_offset and statements_offset + statement_count * 8 <= len(data)):
        return set()
    if not (0 <= definitions_offset and definitions_offset + definition_count * 8 <= len(data)):
        return set()
    if not (0 <= globals_offset and globals_offset + global_count * 4 <= len(data)):
        return set()
    function_global_offsets: dict[int, str] = {}
    for type_and_flags, global_offset, _name in struct.iter_unpack("<HHi", data[definitions_offset : definitions_offset + definition_count * 8]):
        if type_and_flags & ~SAVE_GLOBAL_FLAG != TYPE_FUNCTION or global_offset >= global_count:
            continue
        (function_index,) = struct.unpack_from("<i", data, globals_offset + global_offset * 4)
        if function_index in function_names_by_index:
            function_global_offsets[global_offset] = function_names_by_index[function_index]
    referenced = set()
    for _operation, operand_a, operand_b, operand_c in struct.iter_unpack("<HHHH", data[statements_offset : statements_offset + statement_count * 8]):
        for operand in (operand_a, operand_b, operand_c):
            name = function_global_offsets.get(operand)
            if name:
                referenced.add(name)
    return referenced


def build_game_code(strings: list[str], function_names: list[str]) -> bytes:
    """Builds a minimal, valid version 6 game code file (no statements are executed).
    Used for the self-made demo data and tests."""
    string_block = bytearray(b"\0")
    offsets = {}
    for text in strings + function_names + ["demo.qc"]:
        if text not in offsets:
            offsets[text] = len(string_block)
            string_block += text.encode("latin-1") + b"\0"
    header_size = struct.calcsize(HEADER_FORMAT)
    functions = bytearray(struct.pack(FUNCTION_FORMAT, 0, 0, 0, 0, 0, 0, 0, *([0] * 8)))  # function 0 is always empty
    for name in function_names:
        functions += struct.pack(FUNCTION_FORMAT, 1, 0, 0, 0, offsets[name], offsets["demo.qc"], 0, *([0] * 8))
    statements = struct.pack("<Hhhh", 0, 0, 0, 0)  # one "done" statement
    statements_offset = header_size
    functions_offset = statements_offset + len(statements)
    strings_offset = functions_offset + len(functions)
    globals_offset = strings_offset + len(string_block)
    header = struct.pack(
        HEADER_FORMAT,
        PROGS_VERSION,
        0,
        statements_offset,
        1,
        globals_offset,
        0,
        globals_offset,
        0,
        functions_offset,
        len(function_names) + 1,
        strings_offset,
        len(string_block),
        globals_offset,
        0,
        0,
    )
    return header + statements + bytes(functions) + bytes(string_block)
