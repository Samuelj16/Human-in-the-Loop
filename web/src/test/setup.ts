import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// RTL does not auto-clean under globals:true with this setup, and a leaked
// DOM between cases makes getByRole ambiguous rather than failing loudly.
afterEach(cleanup);
