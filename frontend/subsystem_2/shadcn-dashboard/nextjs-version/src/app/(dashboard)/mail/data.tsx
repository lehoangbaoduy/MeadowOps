export type Mail = {
  id: string
  name: string
  email: string
  subject: string
  text: string
  date: string
  read: boolean
  labels: string[]
}

export const mails: Mail[] = []

export type Account = {
  label: string
  email: string
  icon: React.ReactNode
}

export const accounts: Account[] = []

export type Contact = {
  name: string
  email: string
}

export const contacts: Contact[] = []
