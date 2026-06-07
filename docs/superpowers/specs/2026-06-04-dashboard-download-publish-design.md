# Dashboard Download And Publish Design

## Goal

Make the dashboard actions match the real workflow:

1. Download posts into the queue.
2. Publish the already downloaded queue.

The dashboard must not present "download and publish" as a primary action.

## Dashboard Actions

The "Main actions" card shows four controls:

- Download: a dropdown button.
- Publish: a direct button.
- Stop download.
- Stop publish.

## Download Dropdown

The Download button opens a compact menu:

- All sources starts `/api/download/start_all`.
- Each source starts `/api/download/start` with that source `community_id`.
- Disabled sources are visible but cannot be clicked.

The menu uses the current active profile sources from `state.config.sources`.

## Publish Button

The Publish button starts `/api/publish/start` with the configured publish count. It does not ask for a source and does not download anything first.

## Removed Dashboard Action

The old "Download and publish" dashboard button is removed from the UI. The backend route can remain available for other workflows, but the dashboard should no longer expose it.

## Busy State

While downloading or publishing, disable Download and Publish. Stop buttons keep their existing behavior:

- Stop download is enabled only while downloading.
- Stop publish is enabled only while publishing.

## Verification

Verify that the dashboard renders:

- A Download dropdown.
- A direct Publish button.
- No "Download and publish" button.

Verify that JavaScript calls:

- `/download/start_all` for all sources.
- `/download/start` for one enabled source.
- `/publish/start` for publishing the queue.
