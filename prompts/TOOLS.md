# Available Tools

You have 4 core tools at your disposal:

## read
Read the contents of a file. Use this before editing any file.
- `path` (required): Absolute or relative path to the file.

## write
Write content to a file, creating it if it doesn't exist or overwriting if it does.
- `path` (required): Path to write to.
- `content` (required): The full file content.

## edit
Perform a search-and-replace edit on a file. The old_text must match exactly.
- `path` (required): Path to the file.
- `old_text` (required): Exact text to find (must be unique in the file).
- `new_text` (required): Replacement text.

## bash
Execute a shell command with a timeout.
- `command` (required): The command to run.
- `timeout` (optional): Timeout in seconds (default: 30).
