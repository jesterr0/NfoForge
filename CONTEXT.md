# Context

Glossary for NfoForge. Terms only — no implementation detail, no decisions.

## Group tag

The group name printed on the output: filename, NFO, tracker release title.
It is the identity the user publishes under, so it belongs to the user rather
than to any one release or media type.

A release has at most one group tag. Where none resolves, some trackers
substitute a placeholder of their own rather than printing nothing.

## Source group

The group name read out of an input filename — whoever produced the file the
user is working from. It is a claim: the filename asserts it and nothing can
verify it.

A source group is not a [group tag](#group-tag). It becomes one only when the
user accepts it as their own. Conflating the two is how another group's tag
reaches a user's upload.
