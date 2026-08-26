import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CitationAudit } from "@/components/CitationAudit";
import type { CitationReport } from "@/lib/api";

function report(over: Partial<CitationReport> = {}): CitationReport {
  return {
    cited_count: 3,
    verified_count: 3,
    unverified_count: 0,
    unused_count: 0,
    is_clean: true,
    verified_ratio: 1,
    verified: [],
    unverified: [],
    unused: [],
    ...over,
  };
}

describe("CitationAudit", () => {
  it("says there was nothing to verify when the report cites no links", () => {
    render(<CitationAudit report={report({ cited_count: 0, verified_count: 0 })} />);
    expect(screen.getByText(/cites no links/i)).toBeInTheDocument();
  });

  it("mentions unused retrieved sources even when nothing was cited", () => {
    render(
      <CitationAudit
        report={report({ cited_count: 0, verified_count: 0, unused_count: 2 })}
      />,
    );
    expect(screen.getByText(/2 retrieved source\(s\) went unused/i)).toBeInTheDocument();
  });

  it("reports a clean audit without listing any URLs", () => {
    render(<CitationAudit report={report()} />);
    expect(screen.getByText("All 3 cited links verified")).toBeInTheDocument();
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });

  it("uses the singular when exactly one link was cited", () => {
    render(<CitationAudit report={report({ cited_count: 1, verified_count: 1 })} />);
    expect(screen.getByText("All 1 cited link verified")).toBeInTheDocument();
  });

  it("names every invented URL rather than only counting them", () => {
    // The whole point of the audit is that an unverified citation is visible
    // and checkable, so the URLs themselves have to reach the DOM.
    render(
      <CitationAudit
        report={report({
          verified_count: 1,
          unverified_count: 2,
          is_clean: false,
          unverified: ["https://made-up.org/paper", "https://invented.example/study"],
        })}
      />,
    );

    expect(
      screen.getByText("2 of 3 cited links could not be verified"),
    ).toBeInTheDocument();
    expect(screen.getByText("https://made-up.org/paper")).toBeInTheDocument();
    expect(screen.getByText("https://invented.example/study")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("shows the verified ratio and the uncited-source count", () => {
    render(
      <CitationAudit
        report={report({
          verified_count: 2,
          unverified_count: 1,
          unused_count: 4,
          verified_ratio: 2 / 3,
          is_clean: false,
          unverified: ["https://x.test/a"],
        })}
      />,
    );
    expect(screen.getByText("2/3")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });
});
