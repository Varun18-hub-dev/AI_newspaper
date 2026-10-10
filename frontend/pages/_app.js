import '../styles/globals.css';
import Head from 'next/head';

export default function App({ Component, pageProps }) {
  return (
    <>
      <Head>
        <title>The Curated Dispatch — Personalized AI Newspaper</title>
        <meta name="description" content="Daily multi-source news discovery powered by local Qwen and semantic story clustering." />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
      </Head>
      <Component {...pageProps} />
    </>
  );
}
