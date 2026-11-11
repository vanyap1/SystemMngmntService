# Documentation

Notes, how-tos and command cheat sheets for the boards and PCs managed with this panel.

## Contents

| Section | Documents |
|---|---|
| **Linux** | [systemd services and logs](linux/systemd-and-logs.md) · [Devices, udev, kernel](linux/devices-udev.md) · [Storage, images, backups](linux/storage-backup.md) · [Users and SSH keys](linux/users-ssh.md) · [Python](linux/python.md) |
| **Network** | [Linux network and SMB](network/linux-network.md) · [Windows network tools](network/windows-network.md) |
| **Testing** | [Test platform: operators, parameters, dialogs, logs, debugging](testing/test-platform.md) · [Power supply PSU_CUSTOM6020](testing/psu-custom6020.md) |
| **Hardware** | [Orange Pi 3B power button](hardware/orangepi3b-power.md) · [USB camera streaming](hardware/video-streaming.md) · [Quectel M66 AT commands](hardware/quectel-m66-at.md) · [Schematic ideas](hardware/schematic-ideas.md) |

## How to write documents

Documents are Markdown files in `help/`. Folders in `help/` become sections in the sidebar.

| Folder | Content |
|---|---|
| `help/*.md`, `help/<folder>/*.md` | documents (up to 3 folder levels) |
| `help/img/` | images — paste (Ctrl+V) or drop them into the editor |
| `help/docs/` | attached files — drop them into the editor or use the 📎 button |
| `help/diagrams/` | pinouts / block diagrams — **Diagrams** group in the sidebar, embedded as `.svg` |
| `help/examples/` | raw notes, not shown in the sidebar |
| `help/.trash/` | deleted documents and files |

Links are **relative to the document**, so they also work in VS Code, Git and other Markdown viewers:

```markdown
![Board photo](img/board.png)             <!-- from help/index.md -->
![Board photo](../img/board.png)          <!-- from help/linux/x.md -->
[Firmware](../docs/firmware.zip)          <!-- attachment: shown as a file button -->
[Network](../network/linux-network.md)    <!-- another document -->
[udev section](devices-udev.md#udev-rules)
```

Moving a document to another folder (Rename) fixes its `img/` and `docs/` links automatically.

### Diagrams

Pinouts and block diagrams are drawn in the built-in editor (**Diagrams** in the sidebar, `+` = new).
Every save also writes `diagrams/<name>.svg`; insert it into a page with the diagram button of the editor toolbar:

```markdown
![Board I/O](../diagrams/orangepi3b_io.svg)
```

Hovering a diagram in a page shows **Edit diagram**. Example: [Orange Pi 3B](hardware/orangepi3b-power.md).

| In the editor | |
|---|---|
| `V` `B` `W` `C` `T` `L` | select, block, wire, chip, text, legend |
| drag from block to block (Wire) | arrow attached to both blocks — it follows when they move |
| double-click a wire / bend point | add / remove a bend point |
| double-click a chip | pin table — paste rows from Excel (pin, port, function, kind, dir, note) |
| Space-drag / right-drag, wheel | pan, zoom · `F` fit · `Alt` no snapping |
| `Ctrl+D`, `Del`, `Ctrl+Z` / `Ctrl+Y`, `Ctrl+S` | duplicate, delete, undo / redo, save |

### Formatting cheat sheet

| Markdown | Result |
|---|---|
| `**bold**`, `*italic*`, `~~strike~~` | **bold**, *italic*, ~~strike~~ |
| `` `code` `` | `code` |
| ` ```bash ` … ` ``` ` | code block with highlighting and a Copy button |
| `- [ ] task` / `- [x] done` | task list |
| `> [!NOTE]`, `> [!TIP]`, `> [!WARNING]`, `> [!CAUTION]` | coloured note boxes |

> [!TIP]
> Keyboard: `/` — search, `E` — edit, `Ctrl+S` — save, `Ctrl+B` / `Ctrl+I` / `Ctrl+K` — bold / italic / link.

> [!WARNING]
> Do not keep real passwords in documents — they are plain text files readable by anyone with access to the panel or the disk.
