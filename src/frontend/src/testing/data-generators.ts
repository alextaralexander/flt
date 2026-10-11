// Генераторы тестовых данных на @faker-js/faker (ADR-005, 3.1: faker заменяет
// @ngneat/falso, на нём же строятся моки orval).
import { faker } from '@faker-js/faker';

const generateUser = () => ({
  id: faker.string.uuid() + Math.random(),
  firstName: faker.internet.username().replace(/[^A-Za-z0-9]/g, ''),
  lastName: faker.internet.username().replace(/[^A-Za-z0-9]/g, ''),
  email: faker.internet.email(),
  password: faker.internet.password({ length: 12 }),
  teamId: faker.string.uuid(),
  teamName: faker.company.name(),
  role: 'ADMIN',
  bio: faker.lorem.paragraph(),
  createdAt: Date.now(),
});

export const createUser = <T extends Partial<ReturnType<typeof generateUser>>>(
  overrides?: T,
) => {
  return { ...generateUser(), ...overrides };
};

const generateTeam = () => ({
  id: faker.string.uuid(),
  name: faker.company.name(),
  description: faker.lorem.paragraph(),
  createdAt: Date.now(),
});

export const createTeam = <T extends Partial<ReturnType<typeof generateTeam>>>(
  overrides?: T,
) => {
  return { ...generateTeam(), ...overrides };
};

const generateDiscussion = () => ({
  id: faker.string.uuid(),
  title: faker.company.catchPhrase(),
  body: faker.lorem.paragraph(),
  createdAt: Date.now(),
});

export const createDiscussion = <
  T extends Partial<ReturnType<typeof generateDiscussion>>,
>(
  overrides?: T & {
    authorId?: string;
    teamId?: string;
  },
) => {
  return { ...generateDiscussion(), ...overrides };
};

const generateComment = () => ({
  id: faker.string.uuid(),
  body: faker.lorem.paragraph(),
  createdAt: Date.now(),
});

export const createComment = <
  T extends Partial<ReturnType<typeof generateComment>>,
>(
  overrides?: T & {
    authorId?: string;
    discussionId?: string;
  },
) => {
  return { ...generateComment(), ...overrides };
};
