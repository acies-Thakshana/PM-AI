// plotly.js-dist-min ships the same runtime API as plotly.js (a pre-built,
// smaller bundle covering the common trace types) but no type declarations
// of its own -- reuse @types/plotly.js's types for it.
declare module "plotly.js-dist-min" {
  import Plotly = require("plotly.js");
  export = Plotly;
}
