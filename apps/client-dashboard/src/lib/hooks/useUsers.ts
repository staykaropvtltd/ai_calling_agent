import { useQuery } from "@tanstack/react-query";
import { getUser, listUsers, type UserListParams } from "../api/users";

const KEY = "users";

export function useUsersQuery(params: UserListParams, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: [KEY, params],
    queryFn: () => listUsers(params),
    enabled: options.enabled,
  });
}

export function useUserQuery(userId: string | undefined) {
  return useQuery({
    queryKey: [KEY, userId],
    queryFn: () => getUser(userId as string),
    enabled: Boolean(userId),
  });
}
