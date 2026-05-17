# Claude Desktop MCP Setup

## Quick Configuration

Add the following to your Claude Desktop configuration file:

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
    "mcpServers": {
        "computer-use": {
            "command": "python",
            "args": ["-m", "src.mcp_server"],
            "cwd": "D:/AI/computer use"
        }
    }
}
```

## Or Use the Installed Entry Point

```json
{
    "mcpServers": {
        "computer-use": {
            "command": "computer-use-mcp"
        }
    }
}
```

## Available Tools (11)

| Tool | Description |
|------|-------------|
| `screenshot` | Capture screen as base64 PNG image |
| `get_screen_size` | Get screen width and height |
| `get_display_info` | Get all display information |
| `get_mouse_position` | Get current mouse coordinates |
| `mouse_move` | Move mouse to specified coordinates |
| `click` | Mouse click (left/right/middle, single/double/triple) |
| `type_text` | Type text character by character |
| `key_press` | Press key or combination (e.g. `ctrl+c`) |
| `scroll` | Scroll mouse wheel at coordinates |
| `drag` | Mouse drag from one position to another |
| `wait` | Pause execution for UI response |

## Usage Examples

Once configured in Claude Desktop:

- "Take a screenshot of my desktop"
- "Click at position (500, 300)"
- "Type 'Hello World'"
- "Press ctrl+s to save the file"
- "Drag from (100, 200) to (500, 300)"
- "Scroll down 3 notches"
