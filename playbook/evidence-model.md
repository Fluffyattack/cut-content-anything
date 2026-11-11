# The evidence model

Every item has four independent statements and a separate release history.

| Statement | Supported by | Typical method |
| --- | --- | --- |
| Present in the data | Actual bytes at a stated location in an identified build | Static |
| Possibly unused | Reference analysis with stated coverage | Static |
| Loaded under test conditions | Observation in the actual game, engine or emulator | Runtime |
| Reachable in normal play | An executed ordinary route without debug means | Runtime |

Values: `yes`, `no`, `likely`, `unlikely`, `unknown`, `not checked`,
`not analysed`. Each value carries a basis and a method.

Why separate them? Because they fail independently. A file can be present and
used; present, unused and loadable; unused but impossible to load; or even
reachable in normal play through a route nobody checked. Merging them produces
claims like "unreleased cut level" that no single check supports.

The finding card in the gallery shows the strongest supported wording, for
example **Included in the release · Direct launch tested · No regular access found**.
"Possible cut content" is only a search category.

The directory uses the same statements (with `yes`, `no`, `unknown`) plus a
quality level: `source-reports`, `data-verified`, `runtime-verified`.
