<?php

namespace App\Traits;

use Illuminate\Database\Eloquent\Builder;
use Illuminate\Http\Request;
use Illuminate\Http\JsonResponse;
use Illuminate\Database\Eloquent\ModelNotFoundException;
use Illuminate\Auth\Access\AuthorizationException;
use Symfony\Component\HttpKernel\Exception\NotFoundHttpException;

trait CrudOperations
{
    /**
     * 공통 쿼리 처리
     */
    protected function applyCommonQuery(Builder $query, Request $request): Builder
    {
        // with 관계 처리
        if ($request->has('with')) {
            $withParam = $request->input('with');
            if (!is_null($withParam)) {
                // with 는 모델의 메소드 이므로 카멜케이스 그대로
                $relations = array_filter(explode(',', $withParam));
                $query->with($relations);
            }
        }

        // 검색 조건 처리
        if ($request->has('search')) {
            $search = $request->input('search');
            if ($search) {
                $searchConditions = explode('||', $search);
                foreach ($searchConditions as $condition) {
                    $parts = explode(':', $condition);
                    $parts[0] = \Str::snake($parts[0]);

                    if (count($parts) === 2) {
                        // 2항 조건: field:value
                        $query->where($parts[0], $parts[1]);
                    } elseif (count($parts) === 3) {
                        // 3항 조건: field:operator:value
                        $field = $parts[0];
                        $operator = $parts[1];
                        $value = $parts[2];

                        if ($operator === 'in') {
                            $value = explode(',', $value);
                            $query->whereIn($field, $value);
                        } else if ($operator === 'like') {
                            // like 연산자에서 콤마로 구분된 여러 값 처리
                            $likeValues = explode(',', $value);
                            
                            if (count($likeValues) > 1) {
                                // 여러 값이 있는 경우 OR 조건으로 처리
                                $query->where(function($q) use ($field, $likeValues) {
                                    foreach ($likeValues as $likeValue) {
                                        $likeValue = trim($likeValue);
                                        if (!str_contains($likeValue, '%')) {
                                            $likeValue = "%{$likeValue}%";
                                        }
                                        $q->orWhere($field, 'like', $likeValue);
                                    }
                                });
                            } else {
                                // 단일 값인 경우 기존 로직
                                if (!str_contains($value, '%')) {
                                    $value = "%{$value}%";
                                }
                                $query->where($field, $operator, $value);
                            }
                        } else {
                            $query->where($field, $operator, $value);
                        }

                    }
                }
            }
        }

        // 정렬 처리
        if ($request->has('order')) {
            $orderConditions = explode('||', $request->input('order'));
            foreach ($orderConditions as $condition) {
                $parts = explode(':', $condition);
                if (count($parts) === 2) {
                    $field = \Str::snake($parts[0]);
                    $direction = strtolower($parts[1]) === 'desc' ? 'desc' : 'asc';
                    $query->orderBy($field, $direction);
                }
            }
        }

        return $query;
    }

    /**
     * 기본 목록 조회 메소드
     */
    protected function indexQuery(Request $request, Builder $query): JsonResponse
    {
        try {
            $query = $this->applyCommonQuery($query, $request);

            $items = $query->latest()
                ->paginate($request->input('per_page', 15));

            return $this->paginatedResponse($items);
        } catch (AuthorizationException $e) {
            return response()->json(['message' => '권한이 없습니다.'], 403);
        } catch (\Exception $e) {
            if ($e->getCode() >= 100 && $e->getCode() <= 500) {
                return response()->json([
                    'message' => $e->getMessage(),
                    'code' => $e->getCode(),
                ], $e->getCode());
            }
            return response()->json([
                'message' => '처리 중 오류가 발생했습니다.',
                'error' => $e->getMessage()
            ], 500);
        }
    }

    /**
     * 페이지네이션 응답 생성
     */
    protected function paginatedResponse($items): JsonResponse
    {
        return response()->json([
            'data' => $items->items(),
            'meta' => [
                'current_page' => $items->currentPage(),
                'last_page' => $items->lastPage(),
                'per_page' => $items->perPage(),
                'total' => $items->total(),
            ],
        ]);
    }

    /**
     * 단일 항목 조회
     */
    protected function showQuery(string $id, Request $request): JsonResponse
    {
        try {
            $query = $this->model::query();
            $query = $this->applyCommonQuery($query, $request);

            $item = $query->findOrFail($id);
            return response()->json(['data' => $item]);
        } catch (ModelNotFoundException $e) {
            return response()->json(['message' => '해당 항목을 찾을 수 없습니다.'], 404);
        } catch (AuthorizationException $e) {
            return response()->json(['message' => '권한이 없습니다.'], 403);
        } catch (\Exception $e) {
            if ($e->getCode() >= 100 && $e->getCode() <= 500) {
                return response()->json([
                    'message' => $e->getMessage(),
                    'code' => $e->getCode(),
                ], $e->getCode());
            }
            return response()->json([
                'message' => '처리 중 오류가 발생했습니다.',
                'error' => $e->getMessage()
            ], 500);
        }
    }

    /**
     * 항목 생성
     */
    protected function storeQuery(array $data, array $with = []): JsonResponse
    {
        try {
            $item = $this->model::create($data);

            if (!empty($with)) {
                $item->load($with);
            }

            return response()->json([
                'message' => '생성되었습니다.',
                'data' => $item,
            ], 201);
        } catch (AuthorizationException $e) {
            return response()->json(['message' => '권한이 없습니다.'], 403);
        } catch (\Exception $e) {
            if ($e->getCode() >= 100 && $e->getCode() <= 500) {
                return response()->json([
                    'message' => $e->getMessage(),
                    'code' => $e->getCode(),
                ], $e->getCode());
            }
            return response()->json([
                'message' => '처리 중 오류가 발생했습니다.',
                'error' => $e->getMessage()
            ], 500);
        }
    }

    /**
     * 항목 수정
     */
    protected function updateQuery(string $id, array $data, array $with = []): JsonResponse
    {
        try {
            $item = $this->model::findOrFail($id);
            $item->update($data);

            if (!empty($with)) {
                $item->load($with);
            }

            return response()->json([
                'message' => '수정되었습니다.',
                'data' => $item,
            ]);
        } catch (ModelNotFoundException $e) {
            return response()->json(['message' => '해당 항목을 찾을 수 없습니다.'], 404);
        } catch (AuthorizationException $e) {
            return response()->json(['message' => '권한이 없습니다.'], 403);
        } catch (\Exception $e) {
            if ($e->getCode() >= 100 && $e->getCode() <= 500) {
                return response()->json([
                    'message' => $e->getMessage(),
                    'code' => $e->getCode(),
                ], $e->getCode());
            }
            return response()->json([
                'message' => '처리 중 오류가 발생했습니다.',
                'error' => $e->getMessage()
            ], 500);
        }
    }

    /**
     * 항목 삭제
     */
    protected function destroyQuery(string $id): JsonResponse
    {
        try {
            $item = $this->model::findOrFail($id);
            $item->delete();

            return response()->json([
                'message' => '삭제되었습니다.',
            ]);
        } catch (ModelNotFoundException $e) {
            return response()->json(['message' => '해당 항목을 찾을 수 없습니다.'], 404);
        } catch (AuthorizationException $e) {
            return response()->json(['message' => '권한이 없습니다.'], 403);
        } catch (\Exception $e) {
            if ($e->getCode() >= 100 && $e->getCode() <= 500) {
                return response()->json([
                    'message' => $e->getMessage(),
                    'code' => $e->getCode(),
                ], $e->getCode());
            }
            return response()->json([
                'message' => '처리 중 오류가 발생했습니다.',
                'error' => $e->getMessage()
            ], 500);
        }
    }
}
