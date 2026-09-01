<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class RequestDocsCleanupMiddleware
{
    /**
     * Handle an incoming request.
     *
     * @param  \Closure(\Illuminate\Http\Request): (\Symfony\Component\HttpFoundation\Response)  $next
     */
    public function handle(Request $request, Closure $next): Response
    {
        $response = $next($request);

        // request-docs 경로가 아닌 경우에만 _lrd 데이터 제거
        if (!str_starts_with($request->path(), 'request-docs')) {
            if ($response->headers->get('content-type') === 'application/json' ||
                str_contains($response->headers->get('content-type', ''), 'application/json')) {

                $content = $response->getContent();
                $data = json_decode($content, true);

                if (is_array($data) && isset($data['_lrd'])) {
                    // _lrd 키 제거
                    unset($data['_lrd']);
                    $response->setContent(json_encode($data));
                }
            }
        }

        return $response;
    }
}
