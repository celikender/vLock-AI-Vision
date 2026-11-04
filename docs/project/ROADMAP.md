# Roadmap

Ideas for after the hackathon. None of this is built. For what exists, see the
[overview](OVERVIEW.md) and [test results](../testing/TEST_RESULTS.md).

## Product

- Prove the full chain in real Ignition: UDT import, fixed tags, latch and a machine response.
- The standalone worker-lock lifecycle, kept separate from AI inhibits.
- More than one camera and more than one monitoring job.
- A real accuracy benchmark on plant footage, and long-duration runs.
- A one-step installer, since today's install is a developer setup.
- A no-GPU Docker setup. Docker currently starts the GPU worker container too.

## Giving Muse better knowledge

Today Muse receives a short reference with each request: the always-on notes in `skills/_site/knowledge.md`,
which hold measured phrase scores and engine times, plus any skill matched by keyword. It is not a full
retrieval system. Next steps:

- Search the test results and edge cases and pass only what relates to the request, instead of a fixed short note.
- Update the notes automatically from `sam_latency.csv` and from the scores seen on each camera, so Muse can
  say what has actually worked on that site.
- Show the user why a phrase was suggested and what evidence supports it.

**Research agent (idea only).** A Muse agent could periodically look for other public SAM 3.1 projects and their
published results, then propose additions to the notes. A person should review each proposal. Outside content
is data and must not be treated as instructions, licenses need checking, and results from other sites may not
apply to these cameras.

## Rules and detection

- A local box-inside-person check as a fallback for "wearing" and "holding" rules. It needs no extra API call, but
  it only proves overlap, so an item right next to a person could pass.
- Test relational phrases such as `person wearing safety vest` with the item on, and off but in view.

## Meta connection

- Reopen the connection periodically, so that a blocked name also shows as Unknown. See the
  [edge cases](../testing/EDGE_CASES.md).

## Deployment

A cloud and edge design was discussed: a small agent on the plant network sends frames out over HTTPS, a stateless
inference service runs on a cloud GPU, Jetson or on-premises GPU, and the plant has no inbound ports. Its open
questions are latency, where the UI and Muse live, and what a brief internet drop should do to a machine.

## Repositories

Split `demo_site/` into its own repositories: the Pi camera service, and the printer project with its connector.
