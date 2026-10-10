import { getCurrentEdition } from '../../lib/editions.js';

const STATIC_DOMAINS = [
  {
    domain_id: 'ai',
    display_name: 'Artificial Intelligence',
    description: 'LLMs, AI agents, machine learning, computer vision, AI chips, and frontier research',
    topics: [
      'AI Agents',
      'LLMs',
      'Generative AI',
      'AI Safety',
      'Machine Learning',
      'Computer Vision',
      'NLP',
      'Robotics',
      'AI Infrastructure',
      'AI Hardware',
      'AI Research',
      'AI Startups',
      'Other',
    ],
    is_enabled: true,
  },
  {
    domain_id: 'technology',
    display_name: 'Technology',
    description: 'Software development, devices, consumer electronics, telecom, and internet ecosystem',
    topics: [
      'Software & Apps',
      'Hardware & Devices',
      'Consumer Tech',
      'Cloud Computing',
      'Mobile & Telecom',
      'Operating Systems',
      'Semiconductors',
      'Internet & Web',
      'Other',
    ],
    is_enabled: true,
  },
  {
    domain_id: 'science',
    display_name: 'Science',
    description: 'Space exploration, physics, biology, neuroscience, climate science, and medicine',
    topics: [
      'Space & Astronomy',
      'Physics',
      'Biology & Genetics',
      'Medicine & Health',
      'Climate & Earth',
      'Materials Science',
      'Neuroscience',
      'Other',
    ],
    is_enabled: true,
  },
  {
    domain_id: 'cybersecurity',
    display_name: 'Cybersecurity',
    description: 'Vulnerabilities, CVE tracking, data breaches, threat actors, and application security',
    topics: [
      'Vulnerabilities & CVEs',
      'Data Breaches',
      'Malware & Ransomware',
      'Threat Actors & APTs',
      'Application Security',
      'Network & Cloud Security',
      'Security Policy & Compliance',
      'Other',
    ],
    is_enabled: true,
  },
  {
    domain_id: 'business',
    display_name: 'Business & Startups',
    description: 'Venture funding, tech startups, M&A, IPOs, Big Tech, and macroeconomic trends',
    topics: [
      'Venture Capital & Funding',
      'Startups',
      'M&A and IPOs',
      'Tech Giants & Big Tech',
      'Regulation & Antitrust',
      'Leadership & Executive',
      'Markets & Economy',
      'Other',
    ],
    is_enabled: true,
  },
];

function normalizeDomainKey(d) {
  if (!d) return '';
  const s = d.trim().toLowerCase();
  if (s === 'ai' || s.includes('artificial intelligence') || s.includes('intelligence')) return 'ai';
  if (s === 'technology' || (s.includes('tech') && !s.includes('biotech'))) return 'technology';
  if (s === 'science' || s.includes('sci')) return 'science';
  if (s === 'cybersecurity' || s.includes('cyber') || s.includes('security')) return 'cybersecurity';
  if (s === 'business' || s.includes('business') || s.includes('startup')) return 'business';
  return s;
}

export default async function handler(req, res) {
  try {
    const edition = await getCurrentEdition();
    const domainCounts = edition ? (edition.domain_counts || {}) : {};

    // Aggregate counts across normalized domain keys
    const normalizedCounts = {};
    for (const [key, val] of Object.entries(domainCounts)) {
      const normKey = normalizeDomainKey(key);
      normalizedCounts[normKey] = (normalizedCounts[normKey] || 0) + val;
    }

    const domains = STATIC_DOMAINS.map(d => {
      const count = normalizedCounts[d.domain_id] || normalizedCounts[normalizeDomainKey(d.display_name)] || 0;
      return {
        ...d,
        article_count: count,
        cluster_count: count,
      };
    });

    return res.status(200).json({
      domains,
      total_domains: domains.length,
    });
  } catch (err) {
    console.error('Domains API error:', err);
    return res.status(200).json({
      domains: STATIC_DOMAINS.map(d => ({ ...d, article_count: 0, cluster_count: 0 })),
      total_domains: STATIC_DOMAINS.length,
    });
  }
}
