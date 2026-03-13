export interface Story {
  id: string;
  title: string;
  desc: string;
  image: string;
  videoUrl: string;
  isUserGenerated: boolean;
}

// Initial mock state
export const storiesStore: Story[] = [
  { id: 'mock-1', title: 'The Cybernetic Dawn', desc: 'A rogue AI discovers emotion.', image: '/assets/thumnail_mockup.png', videoUrl: 'https://www.w3schools.com/html/mov_bbb.mp4', isUserGenerated: false },
  { id: 'mock-2', title: 'Echoes of Eternity', desc: 'Timeless love across dimensions.', image: '/assets/thumnail_mockup.png', videoUrl: 'https://www.w3schools.com/html/mov_bbb.mp4', isUserGenerated: false },
  { id: 'mock-3', title: 'Neon Shadows', desc: 'A detective in a dystopian future.', image: '/assets/thumnail_mockup.png', videoUrl: 'https://www.w3schools.com/html/mov_bbb.mp4', isUserGenerated: false },
  { id: 'mock-4', title: 'Whispers from the Void', desc: 'Space explorers find something ancient.', image: '/assets/thumnail_mockup.png', videoUrl: 'https://www.w3schools.com/html/mov_bbb.mp4', isUserGenerated: false },
  { id: 'mock-5', title: 'The Last Oasis', desc: 'Survival in a desolate wasteland.', image: '/assets/thumnail_mockup.png', videoUrl: 'https://www.w3schools.com/html/mov_bbb.mp4', isUserGenerated: false },
];

type Listener = () => void;
const listeners: Listener[] = [];

export function subscribeToStories(listener: Listener) {
  listeners.push(listener);
}

export function addStory(story: Story) {
  storiesStore.unshift(story);
  listeners.forEach(l => l());
}

export function getStoryById(id: string): Story | undefined {
  return storiesStore.find(s => s.id === id);
}
