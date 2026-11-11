// Docs → diagram editor with the demo test station; units whose library component changed are refreshed in the
// browser only (nothing is saved) so the picture shows no "outdated" marks
setTimeout(() => { Diagrams.updateUnits(); Diagrams.dirty = false; Diagrams._bar(); Diagrams.render(); }, 2500);
