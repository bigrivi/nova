"""Where providers come from: presets, discovery, and the model snapshot.

Kept apart from ``nova/llm/providers/``, which is about wire protocols. Nothing
here talks to a model: it answers "what can be connected" and "what does it
serve", and both answers are data rather than configuration.

Import the module, not a name from here. Every caller wants one of the three —
``catalogue`` for what a provider last served, ``presets`` for what a vendor
usually looks like, ``discovery`` for asking a provider directly — and a flat
re-export of fifteen names only made the two ``load`` functions look alike and
the import order matter.
"""
