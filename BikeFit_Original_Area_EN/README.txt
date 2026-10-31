BIKEFIT - ORIGINAL GAP AREA TOOL
English portable edition | Windows 10/11 | Intel/AMD x64

QUICK START
1. Extract the entire ZIP into a writable folder. Do not run inside the ZIP.
2. Double-click Start_Tool.cmd.
3. Choose your camera in Chrome or Microsoft Edge.
4. Click Turn on camera and allow camera access.
5. The five largest areas update automatically. Turn off camera to release it.

Python, the model and required libraries are included. No installation,
API key, Codex account or internet connection is required.
If the browser does not open, copy the local address shown by the launcher.
Each computer must start its own copy of the tool. Keep all files together.

RESTORED AREA RULE
Segment bicycles, join upper silhouette points and lower branch tips,
then count each enclosed white region. Sort by TOTAL visible pixel area,
largest first. Same-silhouette enclosed gaps are included. Display up to five
regions of at least 10 pixels squared. Line and bicycle pixels are excluded.
There is no entry-only score, occlusion corridor ranking or bird's-eye model.
The geometry helpers are reused from the established closed-area pipeline.
This restores the original measurement rule; it is not a byte-identical
archive of every historical version of the segmentation/endpoint helpers.

USE
Aim at ONE complete bicycle row. Include handlebars and wheels, with the
nearest wheels towards the bottom. USB and built-in cameras are supported
when exposed by Windows and the browser. Hardware camera switching has not
been verified on every device. Camera frames are processed locally and are
not saved by this tool. Stop the camera or close its browser tab when done.
The local service remains available until its Python process or PC exits.

LIMITS
Areas are image pixels squared, not square metres or verified parking spaces.
Perspective, occlusion and missed/merged detections affect the result.
The ranking measures visible enclosed image area, not whether a bicycle fits.

OPTIONAL PHOTO TEST
runtime\python.exe colour_gap_top5.py "photo.jpg" --out "photo_results"
This saves the original, mask, numbered result, English CSV and JSON locally.

LICENSES
See LICENSE.txt and THIRD_PARTY_NOTICES. Source files are included.
