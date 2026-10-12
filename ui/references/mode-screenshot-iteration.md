# Screenshot-guided iteration
Identify the reference, actual implementation, viewport, zoom and state before comparing.
Translate the complaint into visible differences: hierarchy, density, alignment, typography, color or inconsistency. A screenshot of broken behavior belongs to diagnosis.
Change the responsible visual surface, render it and compare the relevant region. Iterate when visible evidence shows the requested difference remains.
Use realistic content and inspect nearby states affected by shared styles. Report rendering limitations rather than calling an unviewed result verified.
For responsive or sizing defects, inspect both sides of the affected web breakpoint, or a native window's minimum width, minimum height, their combination and normal size. Include reachable transition states when the complaint concerns motion or timing; a final screenshot cannot verify a transition.
Render comparison candidates on the product's actual background with adjacent components and state preserved. Vary only the property being compared so differences can be attributed to the proposed change.
