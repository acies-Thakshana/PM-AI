// What the assistant, the Configure page and the Planner page tell each other through the shared session store.

/** The interview is over (confirmed or skipped): the Planner may plan. It waits for this, so it plans from the answers. */
export const INTERVIEW_DONE_KEY = "chat.interviewDone";

/** The Configure page says whether "Load & continue" can be pressed now, and what is missing when it cannot. */
export const CONFIGURE_STATUS_KEY = "configure.status";
export interface ConfigureStatus {
  canContinue: boolean;
  label: string;
  /** What is missing, when canContinue is false (empty while it is loading). */
  hint: string;
}
export const NOT_READY: ConfigureStatus = { canContinue: false, label: "Load & continue", hint: "" };

/** The assistant raises this counter to press "Load & continue" on the Configure page for the PM. */
export const CONFIGURE_LOAD_KEY = "configure.loadRequest";
