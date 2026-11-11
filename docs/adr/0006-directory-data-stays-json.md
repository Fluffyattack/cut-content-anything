# Directory data stays JSON

The shared directory is stored as `data/directory.json`, not YAML. JSON keeps
the project usable with the Python standard library alone; the validator and the
generated `DIRECTORY.md` make it readable enough for contributors.
