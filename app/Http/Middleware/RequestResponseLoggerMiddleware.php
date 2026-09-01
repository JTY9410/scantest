<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;
use Symfony\Component\HttpFoundation\Response;

class RequestResponseLoggerMiddleware
{
    private string $loggerName;

    public function __construct(string $loggerName = 'default')
    {
        $this->loggerName = $loggerName;
    }

    /**
     * Handle an incoming request.
     */
    public function handle(Request $request, Closure $next, string $loggerName = 'default'): Response
    {
        $this->loggerName = $loggerName;

        // Request 로깅
        $this->logRequest($request);

        // 다음 미들웨어 실행
        $response = $next($request);

        // Response 로깅
        $this->logResponse($response);

        return $response;
    }

    private function logRequest(Request $request): void
    {
        $logData = [
            'middleware_point' => $this->loggerName,
            'type' => 'REQUEST',
            'method' => $request->method(),
            'url' => $request->fullUrl(),
            'headers' => $request->headers->all(),
            'body' => $request->all(),
            'ip' => $request->ip(),
            'user_agent' => $request->userAgent(),
            'timestamp' => now()->toISOString(),
        ];

        Log::channel('middleware')->info("[$this->loggerName] REQUEST", $logData);
    }

    private function logResponse(Response $response): void
    {
        $content = $response->getContent();

        // JSON 응답인 경우 파싱 시도
        $parsedContent = null;
        if ($response->headers->get('Content-Type') &&
            str_contains($response->headers->get('Content-Type'), 'application/json')) {
            $parsedContent = json_decode($content, true);
        }

        $logData = [
            'middleware_point' => $this->loggerName,
            'type' => 'RESPONSE',
            'status_code' => $response->getStatusCode(),
            'headers' => $response->headers->all(),
            'content' => $parsedContent ?: $content,
            'content_length' => strlen($content),
            'timestamp' => now()->toISOString(),
        ];

        Log::channel('middleware')->info("[$this->loggerName] RESPONSE", $logData);
    }
}
