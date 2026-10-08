import { Link } from 'react-router-dom'
import { Logo } from '@/app/layout'
import { ThemeToggle } from '@/components/shared/theme-toggle'

interface Section {
  title: string
  body: string
}

/* Text carried over unchanged from the legacy lab (legacy/static/terms.html, privacy.html):
   TikTok's app review checks these public URLs, so wording and routes are preserved. */
const TERMS: Section[] = [
  { title: '1. Назначение сервиса', body: 'Qadam Media Test предназначен для проверки авторизации TikTok, получения разрешённых параметров аккаунта и отправки выбранного пользователем видео. Отдельные функции находятся в тестовом режиме и могут изменяться.' },
  { title: '2. Доступ и безопасность', body: 'Пользователь отвечает за сохранность пароля стенда, своего TikTok-аккаунта и устройств. Запрещено передавать доступ посторонним лицам, обходить ограничения или вмешиваться в работу сервиса.' },
  { title: '3. Подключение TikTok', body: 'Подключение выполняется через официальный процесс TikTok OAuth. Qadam Media не получает пароль TikTok. Пользователь самостоятельно подтверждает разрешения user.info.basic и video.publish и может отозвать их в настройках TikTok.' },
  { title: '4. Публикация контента', body: 'Перед публикацией пользователь выбирает видео, описание, доступный уровень видимости и явно нажимает кнопку отправки. Пользователь отвечает за содержание, законность, авторские права и соблюдение правил TikTok.' },
  { title: '5. Ограничения тестового приложения', body: 'Неаудированное TikTok-приложение может публиковать только в приватном режиме и иметь дополнительные ограничения. Qadam Media не гарантирует одобрение, время обработки, доступность API, охват или результат публикации.' },
  { title: '6. Запрещённое использование', body: 'Нельзя публиковать незаконные материалы, спам, вредоносный контент, чужие материалы без разрешения, вводящую в заблуждение рекламу или контент, нарушающий права и безопасность других лиц.' },
  { title: '7. Сторонние сервисы', body: 'Работа интеграции зависит от TikTok, хостинга и сетевой инфраструктуры. На использование TikTok также распространяются условия и правила TikTok.' },
  { title: '8. Ответственность', body: 'Сервис предоставляется в доступном виде для тестирования. Ограничения ответственности применяются только в пределах законодательства Республики Казахстан и не отменяют обязательные права пользователя.' },
  { title: '9. Изменения и контакты', body: 'Условия могут обновляться вместе с развитием интеграции. Вопросы можно направить через официальные контактные данные Qadam Media на qadam-media.kz.' },
]

const PRIVACY: Section[] = [
  { title: '1. Какие данные обрабатываются', body: 'Сервис может обрабатывать введённые пользователем данные, технические журналы, IP-адрес, cookie сессии, загруженное видео и описание публикации.' },
  { title: '2. Данные TikTok', body: 'После разрешения пользователя мы можем получить идентификатор аккаунта, отображаемое имя, аватар, перечень разрешений, технические токены доступа, параметры и статус публикации. Qadam Media не получает пароль TikTok.' },
  { title: '3. Цели обработки', body: 'Данные используются для авторизации, проверки подключения, получения разрешённых параметров публикации, передачи видео в TikTok, отображения статуса, диагностики ошибок и защиты сервиса.' },
  { title: '4. Явное действие пользователя', body: 'Видео передаётся TikTok только после выбора файла и нажатия пользователем кнопки публикации. Подключение аккаунта выполняется после подтверждения разрешений на официальной странице TikTok.' },
  { title: '5. Хранение и защита', body: 'Токены TikTok хранятся на сервере в зашифрованном виде и не отображаются в браузере. Мы применяем HTTPS, ограничение доступа и техническое журналирование. Данные хранятся только в течение необходимого периода.' },
  { title: '6. Передача данных', body: 'Данные передаются TikTok и техническим поставщикам только в объёме, необходимом для запрошенной функции. Мы не продаём персональные данные.' },
  { title: '7. Cookie', body: 'Необходимые cookie используются для защищённой сессии, проверки OAuth state и предотвращения несанкционированного доступа.' },
  { title: '8. Управление и удаление', body: 'Пользователь может отключить TikTok в интерфейсе и отозвать разрешения в TikTok. Можно запросить доступ, исправление или удаление данных. Отключение не удаляет видео, уже опубликованные в TikTok.' },
  { title: '9. Трансграничная передача', body: 'TikTok и отдельные технические поставщики могут обрабатывать данные за пределами Республики Казахстан. Передача выполняется с учётом применимых требований и доступных мер защиты.' },
  { title: '10. Обновления и контакты', body: 'Политика может обновляться при изменении интеграции или законодательства. Вопросы можно направить через официальные контактные данные Qadam Media на qadam-media.kz.' },
]

function LegalLayout({ kicker, title, lead, sections }: { kicker: string; title: string; lead: string; sections: Section[] }) {
  return (
    <div className="min-h-dvh">
      <header className="flex items-center justify-between border-b px-4 py-3 sm:px-8">
        <Logo />
        <div className="flex items-center gap-4">
          <ThemeToggle />
          <Link className="text-sm text-primary underline-offset-4 hover:underline" to="/">Вернуться на главную</Link>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
        <article>
          <p className="text-xs font-medium tracking-widest text-primary uppercase">{kicker}</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-balance">{title}</h1>
          <p className="mt-4 text-muted-foreground">{lead}</p>
          <p className="mt-2 text-sm text-muted-foreground">Последнее обновление: 6 октября 2026 года</p>
          {sections.map((s) => (
            <section key={s.title} className="mt-8">
              <h2 className="text-lg font-semibold">{s.title}</h2>
              <p className="mt-2 leading-relaxed text-foreground/90">{s.body}</p>
            </section>
          ))}
        </article>
      </main>
      <footer className="flex flex-col items-center justify-between gap-2 border-t px-4 py-4 text-sm text-muted-foreground sm:flex-row sm:px-8">
        <span>© 2026 Qadam Media</span>
        <nav className="flex gap-4" aria-label="Юридические документы">
          <Link to="/terms">Условия использования</Link>
          <Link to="/privacy">Политика конфиденциальности</Link>
        </nav>
      </footer>
    </div>
  )
}

export function TermsPage() {
  return (
    <LegalLayout
      kicker="QADAM / LEGAL"
      title="Условия использования"
      lead="Эти условия регулируют использование тестового сервиса Qadam Media для подключения TikTok-аккаунта и публикации видео через официальный TikTok API."
      sections={TERMS}
    />
  )
}

export function PrivacyPage() {
  return (
    <LegalLayout
      kicker="QADAM / PRIVACY"
      title="Политика конфиденциальности"
      lead="Эта политика описывает обработку данных в тестовом сервисе Qadam Media при подключении TikTok и публикации видео."
      sections={PRIVACY}
    />
  )
}
