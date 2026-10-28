# Development Workflow

Open the vLock-AI Vision folder in Visual Studio Code. Keep the Explorer, terminal,
and Source Control panel visible so you can read files, run commands, and inspect
changes. A coding agent can edit the same project files while VS Code is open.
Use this project folder as the shared source of truth for implementation and review.

## Where code will live

- playground/: first small, runnable experiments, before app integration.
- services/vision/: camera-frame analysis with Muse Spark and SAM 3.1 segmentation.
- services/vlock/: deterministic rules and application state.
- web/: camera UI, configuration review, and frame overlays.
- integrations/: SCADA adapters.
- docs/: decisions, setup instructions, results, and troubleshooting notes.

## Our working agreement

1. Explain the small step and files involved before implementing it.
2. Implement only that step, with readable names and comments where useful.
3. Provide the exact command to run it and the expected result.
4. Report what was actually tested and any errors or unfinished work.
5. Pause for Ender's review before beginning the next feature.
6. Keep secrets in local ignored environment files. Save working milestones in Git.

If a step fails, keep the error visible, isolate its cause, and fix that step before
adding another feature. Do not describe an untested API connection as working.

## Agreed first camera flow

Camera initializes -> capture one photo -> Muse Spark describes the visible scene
and proposes short object concepts -> SAM 3.1 segments each approved concept in
the same photo -> UI displays masks and boxes on that captured frame.

Attach a capture ID to analysis and segmentation so results stay with the correct
image. Masks from the first photo do not automatically track later video frames;
video tracking will be a separate step.

## Next step to review

Pi streaming and the main UI connection have been confirmed by the owner.
Next, integrate captured-photo model services into the main UI in web/.
Continue all edits and commits in vLock-AI-Vision.

## Coding agent roles and review

Ender assigns and changes roles according to task needs and observed performance.
Any participating coding agent may implement, review, investigate failures, or
validate results. Do not assume a permanent lead or reviewer role.

Keep each task scoped to named files and a clear acceptance criterion. When agents
work at the same time, assign separate files; coordinate before editing shared
files. Review the actual diff and runnable result before accepting a milestone.

Each handoff should state the objective, files changed, commands run, observed
results, known limitations, and the next decision requiring Ender's review.
Independent reviewers should inspect the code and verify the relevant checks.

## Performance evaluation

Evaluate coding agents on comparable tasks using correctness, readable code,
verified results, debugging effectiveness, time, and available usage/cost data.
Record actual observations in the development log. Do not rank an agent based on
unrun tasks or assume access to another agent's private session or results.

Muse's development performance has not been evaluated in this project. Start with
a small task with explicit acceptance criteria and review its output before
assigning broader work. This evaluation is separate from evaluating Muse Spark
as the application's scene-analysis model.


