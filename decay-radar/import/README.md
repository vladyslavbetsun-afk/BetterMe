# import/

Local inputs only; everything here except this README is git-ignored.

- `slipped__pages.json`, `slipped__progress.json`: the old Slipped Pages Tracker export (spec 05 §7), used as calibration labels.
- `already-suggested.md`: the "Article Update Pipeline — Already Suggested (tracking)" doc, pasted or exported. Load it with `python -m decay import-suggested`. URLs are read line by line, and a `#` heading with a YYYY-MM-DD date sets the date for the lines below it.
