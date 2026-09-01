<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\Applog;
use Illuminate\Http\Request;
use Illuminate\Http\JsonResponse;

class ApplogController extends Controller
{
    /**
     * Display a listing of the resource.
     */
    public function index(Request $request): JsonResponse
    {
        $query = Applog::query();

        if ($request->has('search')) {
            $search = $request->get('search');
            $query->where(function ($q) use ($search) {
                $q->where('type', 'like', "%{$search}%")
                    ->orWhere('message', 'like', "%{$search}%")
                    ->orWhere('desc', 'like', "%{$search}%");
            });
        }

        if ($request->has('user_id')) {
            $query->where('user_id', $request->get('user_id'));
        }

        if ($request->has('type')) {
            $query->where('type', $request->get('type'));
        }

        $perPage = $request->get('per_page', 15);
        $logs = $query->orderBy('created_at', 'desc')->paginate($perPage);

        return response()->json($logs);
    }

    /**
     * Store a newly created resource in storage.
     */
    /**
     * @LRDparam timestamp string|required
     * @LRDparam user_id integer|nullable
     * @LRDparam type string|required
     * @LRDparam message string|required
     * @LRDparam desc string|nullable
     * @LRDresponses 200|500
     */
    public function store(Request $request): JsonResponse
    {
        $validated = $request->validate([
            'timestamp' => 'required|date',
            'user_id' => 'nullable|exists:users,id',
            'type' => 'required|string|max:255',
            'message' => 'required|string|max:2000',
            'desc' => 'nullable|string',
        ]);

        $log = Applog::create($validated);

        return response()->json($log, 201);
    }

    /**
     * Display the specified resource.
     */
    public function show(Applog $applog): JsonResponse
    {
        return response()->json($applog);
    }

    /**
     * Update the specified resource in storage.
     */
    public function update(Request $request, string $id)
    {
        //
    }

    /**
     * Remove the specified resource from storage.
     */
    public function destroy(string $id)
    {
        //
    }
}
