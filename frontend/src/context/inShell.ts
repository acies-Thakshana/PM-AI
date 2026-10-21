import { createContext } from "react";

/** True inside the app shell, which already provides the logo and the stage list, so the pages' own
 * Header and StepIndicator render nothing. */
export const InShellContext = createContext(false);
