# Renderer faults

Use when generated output differs from expected runtime behavior. Reproduce with the actual renderer and version; document typesetting alone belongs to the host document tool.
Check loaded fonts, asset paths, CORS, print styles, page dimensions, overflow and break rules. Inspect computed output rather than assuming a CSS feature has identical support across engines.
Use a small failing artifact to distinguish content, stylesheet and renderer-version causes. Verify the corrected output in the affected renderer; browser preview does not prove PDF or print correctness.
