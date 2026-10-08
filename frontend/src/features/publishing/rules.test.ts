import { describe, expect, it } from 'vitest'
import { creator, media } from '@/test/utils'
import { checkFile, initialPublishState, privacyOptions, summarise, toPayload, validatePublish, type PublishFormState } from './rules'

const state = (over: Partial<PublishFormState> = {}): PublishFormState => ({
  ...initialPublishState,
  accountId: 'a1',
  privacy: 'SELF_ONLY',
  musicConsent: true,
  ...over,
})
const ctx = { creator, media, audited: false }

describe('TikTok content sharing guidelines', () => {
  it('has no default privacy and every interaction toggle starts off', () => {
    expect(initialPublishState.privacy).toBe('')
    expect([initialPublishState.allowComment, initialPublishState.allowDuet, initialPublishState.allowStitch]).toEqual([false, false, false])
    expect(initialPublishState.commercial).toBe(false)
    expect(initialPublishState.musicConsent).toBe(false)
  })

  it('cannot submit until a privacy level is chosen', () => {
    const r = validatePublish(state({ privacy: '' }), ctx)
    expect(r.canSubmit).toBe(false)
    expect(r.errors.privacy).toBeTruthy()
  })

  it('requires the music usage confirmation for direct posts only', () => {
    expect(validatePublish(state({ musicConsent: false }), ctx).errors.music).toBeTruthy()
    expect(validatePublish(state({ mode: 'UPLOAD_TO_INBOX', musicConsent: false, privacy: '' }), ctx).canSubmit).toBe(true)
  })

  it('accepts a valid private post', () => {
    expect(validatePublish(state(), ctx)).toEqual({ errors: {}, canSubmit: true })
  })

  it('needs a video and an account', () => {
    expect(validatePublish(state(), { ...ctx, media: null }).errors.video).toBeTruthy()
    expect(validatePublish(state({ accountId: '' }), ctx).errors.account).toBeTruthy()
  })

  it('waits for creator info before allowing submit', () => {
    expect(validatePublish(state(), { ...ctx, creator: undefined }).canSubmit).toBe(false)
  })
})

describe('privacy options', () => {
  it('only lists what Creator Info allows', () => {
    const values = privacyOptions({ ...creator, privacy_level_options: ['SELF_ONLY', 'FOLLOWER_OF_CREATOR'] }, true, false).map((o) => o.value)
    expect(values).toEqual(['SELF_ONLY', 'FOLLOWER_OF_CREATOR'])
    expect(privacyOptions(undefined, true, false)).toEqual([])
  })
  it('limits un-audited apps to SELF_ONLY', () => {
    const opts = privacyOptions(creator, false, false)
    expect(opts.filter((o) => !o.disabled).map((o) => o.value)).toEqual(['SELF_ONLY'])
    expect(opts.find((o) => o.value === 'PUBLIC_TO_EVERYONE')?.reason).toMatch(/аудит/)
    expect(validatePublish(state({ privacy: 'PUBLIC_TO_EVERYONE' }), ctx).errors.privacy).toBeTruthy()
    expect(validatePublish(state({ privacy: 'PUBLIC_TO_EVERYONE' }), { ...ctx, audited: true }).canSubmit).toBe(true)
  })
  it('rejects a privacy level the creator does not offer', () => {
    const limited = { ...ctx, audited: true, creator: { ...creator, privacy_level_options: ['SELF_ONLY' as const] } }
    expect(validatePublish(state({ privacy: 'PUBLIC_TO_EVERYONE' }), limited).errors.privacy).toBeTruthy()
  })
  it('disables SELF_ONLY for branded content', () => {
    const opts = privacyOptions(creator, true, true)
    expect(opts.find((o) => o.value === 'SELF_ONLY')?.disabled).toBe(true)
    expect(opts.find((o) => o.value === 'PUBLIC_TO_EVERYONE')?.disabled).toBe(false)
  })
})

describe('commercial content disclosure', () => {
  it('requires at least one brand option once enabled', () => {
    expect(validatePublish(state({ commercial: true }), ctx).errors.commercial).toBeTruthy()
    expect(validatePublish(state({ commercial: true, brandOrganic: true }), ctx).canSubmit).toBe(true)
  })
  it('does not allow branded content with private visibility', () => {
    const r = validatePublish(state({ commercial: true, brandContent: true, privacy: 'SELF_ONLY' }), ctx)
    expect(r.errors.commercial).toMatch(/Только я/)
    expect(validatePublish(state({ commercial: true, brandContent: true, privacy: 'PUBLIC_TO_EVERYONE' }), { ...ctx, audited: true }).canSubmit).toBe(true)
  })
})

describe('limits', () => {
  it('rejects titles over 2200 characters', () => {
    expect(validatePublish(state({ title: 'x'.repeat(2201) }), ctx).errors.title).toBeTruthy()
    expect(validatePublish(state({ title: 'x'.repeat(2200) }), ctx).errors.title).toBeUndefined()
  })
  it('rejects a video longer than the creator limit', () => {
    const long = { ...media, duration_seconds: 601 }
    expect(validatePublish(state(), { ...ctx, media: long }).errors.duration).toMatch(/600/)
  })
})

describe('payload', () => {
  it('sends only what the user enabled and never beats creator restrictions', () => {
    const restricted = { ...creator, comment_disabled: true }
    const payload = toPayload(state({ allowComment: true, allowDuet: true, title: 'hi' }), 'm1', restricted)
    expect(payload).toMatchObject({ allow_comment: false, allow_duet: true, allow_stitch: false, title: 'hi', media_id: 'm1', account_id: 'a1' })
  })
  it('maps commercial flags and inbox mode', () => {
    expect(toPayload(state({ commercial: true, brandContent: true, brandOrganic: true, privacy: 'PUBLIC_TO_EVERYONE' }), 'm1', creator))
      .toMatchObject({ brand_content_toggle: true, brand_organic_toggle: true })
    expect(toPayload(state({ commercial: false, brandContent: true }), 'm1', creator).brand_content_toggle).toBe(false)
    expect(toPayload(state({ mode: 'UPLOAD_TO_INBOX', privacy: '', allowComment: true }), 'm1', creator))
      .toMatchObject({ mode: 'UPLOAD_TO_INBOX', privacy_level: 'SELF_ONLY', allow_comment: false, music_usage_confirmed: false })
  })
  it('summarises the target for the confirmation dialog', () => {
    expect(summarise(state(), creator)).toContain('@tester')
    expect(summarise(state({ mode: 'UPLOAD_TO_INBOX' }), creator)).toMatch(/черновики/)
  })
})

describe('file pre-checks', () => {
  it.each([
    [{ name: 'a.mp4', type: 'video/mp4', size: 1000 }, true],
    [{ name: 'a.mov', type: 'video/quicktime', size: 1000 }, true],
    [{ name: 'a.webm', type: 'video/webm', size: 1000 }, true],
    [{ name: 'a.MP4', type: '', size: 1000 }, true],
    [{ name: 'a.avi', type: 'video/x-msvideo', size: 1000 }, false],
    [{ name: 'a.exe', type: 'application/x-msdownload', size: 1000 }, false],
    [{ name: 'a.mp4', type: 'video/mp4', size: 0 }, false],
    [{ name: 'a.mp4', type: 'video/mp4', size: 11 * 1024 * 1024 }, false],
  ])('%j -> %s', (file, ok) => {
    expect(checkFile(file, 10).ok).toBe(ok)
  })
})
