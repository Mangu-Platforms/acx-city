import Link from 'next/link'

export default function Home() {
  return (
    <main className="min-h-screen bg-slate-950 text-white">
      <section className="mx-auto flex min-h-screen max-w-5xl flex-col items-start justify-center px-6 py-20">
        <p className="mb-4 text-sm font-semibold uppercase tracking-[0.3em] text-blue-300">
          ACX City
        </p>
        <h1 className="max-w-3xl text-5xl font-bold tracking-tight sm:text-7xl">
          Audiobook production operations, built for scale.
        </h1>
        <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300">
          CoverLabs powers production workflows for audiobook teams, from job queue visibility to quality control and delivery operations.
        </p>
        <div className="mt-10 flex flex-wrap gap-4">
          <Link
            href="/dashboard"
            className="rounded-full bg-blue-500 px-6 py-3 text-sm font-semibold text-white transition hover:bg-blue-400"
          >
            Open ops dashboard
          </Link>
          <a
            href="mailto:hello@coverlabs.app"
            className="rounded-full border border-white/20 px-6 py-3 text-sm font-semibold text-white transition hover:bg-white/10"
          >
            Contact CoverLabs
          </a>
        </div>
      </section>
    </main>
  )
}
