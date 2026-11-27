# Contract documentation

`catalog.json` is the machine-readable public contract index. Each entry names
an owner, producer, consumer, purpose, and semantic notes. Examples live in
`examples/contract_examples.json`; every type has one valid and two invalid
payload descriptions.

The comments in `.msg`, `.srv`, and `.action` files are normative for field
units, bounds, optionality, and invalid-value behavior. The catalog supplements
those definitions with cross-process use cases.
