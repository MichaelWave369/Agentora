# Phi Desktop Bridge R9: Field Readiness inside Operator Desk

R9 adds a separate **Field readiness (read-only)** window to R3's
native local Operator Desk. It reads bounded metadata from the R8 field
journal but does NOT connect the journal to proposal decisions or desktop
actions. A recorded "observed" result is a **self-report**, not approval.

## Visible readiness information

The panel displays whether a local R8 SQLite journal exists, the count of
operator-reported trials, up to 12 recent compact entries, and explicit
NOT VERIFIED checks: real end-user Windows app compatibility, multi-account
pipe-denial testing, independent security review, same-user process
isolation, and user-level task completion.

The words **NOT AUTHORIZED** remain present regardless of the number or
outcome of local reports. The display never calls the broker, updates the
proposal inbox, authorizes an action, or opens a web route.

## Offline operation

This PR can be reviewed, tested and merged entirely on GitHub without
installing or executing anything on a personal Windows desktop.

For an optional local test after choosing to install Agentora, use the
already existing R3 Operator Desk command:

    $env:PYTHONPATH = "server"
    python -m app.services.desktop_operator_desk --policy "examples/desktop-bridge/operator-policy.example.json"

Click **Field readiness (read-only)**. A separate panel opens with a
Refresh local ledger control. If the R8 database does not exist, the
display reads "not_recorded" and must not create a replacement.

The default path is in the current user's profile:
~/.agentora/field-trials/field-journal.db

An alternate existing local journal can be read with the new
--field-db argument. It is not an upload destination or permissions grant.

## Safety boundaries

- The journal is opened via a SQLite URI in mode=ro, with query_only ON.
- Reading does not create a journal, modify R8 data or import raw UI trees.
- The preview includes only predefined issue labels, status, timestamps and
  observation counts. Unknown free-text fields remain hidden.
- Corrupted/inaccessible journals show unavailable_or_insecure. On POSIX
  the file and immediate parent require restrictive owner-only modes.
- Windows user-profile file ACLs are NOT verified in this rung.
- SQLite is not cryptographically signed or independently attested.
- A field report cannot override OperatorPolicy or the R1 manual approval
  requirements. The readiness window has no action or review buttons.
- Same-user malicious programs can forge or tamper with local entries.

## Validation

The R9 tests check that missing files stay missing, tampered "success"
claims remain hidden, invalid database files fail closed, read access does
not mutate the database, and the readiness view never contacts the inbox.
Existing backend Python 3.12/3.13, web build and Windows CI still apply.
A dedicated Windows runner executes the R9 headless tests, not actual
desktop accessibility or GUI interaction.

Future work: supervised non-sensitive Windows field trials and independent
cross-user security tests. Automated desktop execution remains out of scope.
