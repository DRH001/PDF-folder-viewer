# PDF-folder-viewer
A lightweight PDF viewer which uses left/right arrow keys to switch between previous/next PDF files in a folder. Useful e.g. for browsing conference proceedings. Includes a "Flatten subfolders" checkbox which reads PDFs from the selected folder as well as every subfolder. This application does not have the ability to modify any files.

This is useful for switching between hundreds or thousands of PDFs without having to have them all open in separate browser tabs for example. Only one PDF is loaded into memory at a time, so this application is very light on memory usage even for very large numbers of PDFs.

Usage
=
Open pdf_viewer.exe (download this from the "releases" section, or compile it yourself following the instructions in the .py file), then click "Open Folder..." and open a folder where PDFs reside. The software will show a list of all PDFs on the left side of the window. The left/right arrow keys will move between previous/next PDFs in the folder - all other controls are similar to pretty much every other existing PDF viewer. If using the "Fit page" option, use page up/down to navigate.

Disclaimer
=
This code was written partially by AI (because frontend can be mundane). The code itself is simple - it's a basic GUI which can open a folder of PDFs without any bloat/overhead and use the arrow keys to navigate between PDFs. The executable is ~20MB because it packages Qt plugins so that the exe can be standalone.
