import { z } from 'zod'

// Request/response validation (MANGU practice: validate at the boundary with Zod).

export const synthesisRequestSchema = z.object({
  text: z.string().min(1, 'Text is required'),
  provider: z.string().min(1),
  voice_id: z.string().min(1, 'Pick a voice'),
  engine: z.enum(['neural', 'standard']),
  formats: z.array(z.enum(['mp3', 'm4b'])).min(1),
  title: z.string().optional(),
  author: z.string().optional(),
})
export type SynthesisRequestInput = z.infer<typeof synthesisRequestSchema>

export const authResponseSchema = z.object({
  token: z.string(),
  user: z.object({
    id: z.string(),
    email: z.string(),
    display_name: z.string().optional().nullable(),
  }),
  organization: z.object({ id: z.string(), name: z.string() }).optional(),
})

export const signedUrlSchema = z.object({
  url: z.string(),
  expires_in: z.number(),
})

export const credentialsSchema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
})
