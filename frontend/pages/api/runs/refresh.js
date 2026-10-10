export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // In zero-cost / serverless reader mode, on-demand compute is not triggered from reader browsers
  return res.status(202).json({
    run_id: 'scheduled_publication',
    status: 'SCHEDULED',
    message: 'Manual worker execution is disabled on the serverless reader tier. New editions publish daily at 06:00 IST.',
  });
}
