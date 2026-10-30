import "@testing-library/jest-dom/vitest";

// jsdom does not implement scrolling; the router calls it on navigation.
window.scrollTo = () => {};

// jsdom has no modal <dialog> support.
HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
  this.open = true;
};
HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) {
  if (!this.open) return;
  this.open = false;
  this.dispatchEvent(new Event("close")); // as browsers do
};
