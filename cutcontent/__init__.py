"""Cut Content Anything: finds and previews possibly unused content in game data.

The package is organised by purpose:

- ``cutcontent.core``: shared building blocks (folder permissions, read-only file
  access, the evidence model for findings, report storage, the scan service).
- ``cutcontent.formats``: pure readers for file formats (Quake PAK/BSP/MDL, ISO 9660,
  disc images with file tables or tree directories, cartridge headers, ...). They never write anything.
- ``cutcontent.platforms``: one adapter per platform family. An adapter recognises
  a game or build, lists its content, judges what might be unused and prepares previews.
- ``cutcontent.previews``: converts game data into browser-friendly previews
  (PNG images, 3D map and model descriptions).
- ``cutcontent.web``: the local web interface (``cutcontent gui``).
- ``cutcontent.cli``: the command line (``cutcontent doctor``, ``cutcontent scan``, ...).
"""

__version__ = "0.2.0"
