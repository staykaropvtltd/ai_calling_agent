import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createUser,
  deleteUser,
  getUser,
  listUsers,
  updateUser,
  type UserListParams,
} from "../api/users";
import type { CreateUserRequest, UpdateUserRequest } from "../types/user";

const KEY = "users";

export function useUsersQuery(params: UserListParams) {
  return useQuery({
    queryKey: [KEY, params],
    queryFn: () => listUsers(params),
  });
}

export function useUserQuery(userId: string | undefined) {
  return useQuery({
    queryKey: [KEY, userId],
    queryFn: () => getUser(userId as string),
    enabled: Boolean(userId),
  });
}

export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateUserRequest) => createUser(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useUpdateUser(userId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: UpdateUserRequest) => updateUser(userId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useDeleteUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => deleteUser(userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}
