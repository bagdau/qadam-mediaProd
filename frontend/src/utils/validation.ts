export function required(value: string): string | undefined {
  return value.trim() ? undefined : 'Обязательное поле'
}

export function validEmail(value: string): string | undefined {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim()) ? undefined : 'Введите корректный email'
}
