"""Platform adapters, in the order they are asked to recognise a file or folder.

More specific adapters come first; the generic folder adapter is the fallback.
"""

from __future__ import annotations

from cutcontent.platforms.base import PlatformAdapter


def all_adapters() -> list[PlatformAdapter]:
    from cutcontent.platforms.generic_folder import GenericFolderAdapter
    from cutcontent.platforms.generic_artifact import GenericArtifactAdapter
    from cutcontent.platforms.tree_directory_disc import TreeDirectoryDiscAdapter
    from cutcontent.platforms.file_table_disc import FileTableDiscAdapter
    from cutcontent.platforms.cartridge_file_table import CartridgeFileTableAdapter
    from cutcontent.platforms.cartridge_rom import CartridgeRomAdapter
    from cutcontent.platforms.quake_engine import QuakeAdapter
    from cutcontent.platforms.iso9660_disc import Iso9660DiscAdapter

    return [
        QuakeAdapter(),
        CartridgeFileTableAdapter(),
        CartridgeRomAdapter(),
        FileTableDiscAdapter(),
        Iso9660DiscAdapter(),
        TreeDirectoryDiscAdapter(),
        GenericFolderAdapter(),
        GenericArtifactAdapter(),
    ]


def adapter_by_identifier(identifier: str) -> PlatformAdapter:
    for adapter in all_adapters():
        if adapter.identifier == identifier:
            return adapter
    raise KeyError(f"Unknown adapter: {identifier}")
