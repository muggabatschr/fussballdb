import { Suspense } from "react";
import { AbsenceList } from "@/components/AbsenceList";
import { Card, ErrorBox } from "@/components/Card";
import { FormTable } from "@/components/FormTable";
import { TeamName } from "@/components/TeamName";
import { XgChart } from "@/components/XgChart";
import { getAbsences, getForm, load } from "@/lib/api";
import { num } from "@/lib/format";

const stats: [string, string, number][] = [
  ["avg_xg", "xG pro Spiel", 2],
  ["avg_xga", "xGA pro Spiel", 2],
  ["avg_big_chances", "Großchancen", 1],
  ["avg_ppda", "PPDA", 1],
  ["avg_xpts", "xPts pro Spiel", 2],
];

async function Team({ params }: { params: PageProps<"/team/[name]">["params"] }) {
  const team = decodeURIComponent((await params).name);
  const res = await load(() => Promise.all([getForm(team, 10), getAbsences(team)]));
  if (!res.ok) return <ErrorBox message={res.error} />;
  const [form, absences] = res.data;
  const s = form.zusammenfassung;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">
          <TeamName name={team} link={false} logoSize={40} />
        </h1>
        <p className="text-sm text-muted">
          Letzte {s.spiele} Spiele: {s.punkte} Punkte
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {stats.map(([key, label, digits]) => (
          <Card key={key}>
            <div className="text-xs text-muted">{label}</div>
            <div className="text-lg font-semibold tabular">{num(s[key], digits)}</div>
          </Card>
        ))}
      </div>
      <Card>
        <h2 className="mb-2 text-sm font-medium">xG und xGA je Spiel</h2>
        <XgChart games={form.spiele} />
      </Card>
      <section>
        <h2 className="mb-2 text-sm font-medium">Spiele</h2>
        <FormTable games={form.spiele} />
      </section>
      <section>
        <h2 className="mb-2 text-sm font-medium">Ausfälle</h2>
        <AbsenceList rows={absences} />
      </section>
    </div>
  );
}

export default function Page(props: PageProps<"/team/[name]">) {
  return (
    <Suspense fallback={<p className="text-muted">Lade Team …</p>}>
      <Team params={props.params} />
    </Suspense>
  );
}
