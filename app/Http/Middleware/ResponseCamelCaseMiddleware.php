<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;
use Illuminate\Support\Str;

class ResponseCamelCaseMiddleware
{
    /**
     * Handle an incoming request.
     *
     * @param  \Closure(\Illuminate\Http\Request): (\Symfony\Component\HttpFoundation\Response)  $next
     */
    public function handle(Request $request, Closure $next): Response
    {
        $response = $next($request);
        \Log::info('ResponseCamelCaseMiddleware');
        if ($response->getContent()) {
            $content = json_decode($response->getContent(), true);
            if (is_array($content)) {
                $response->setContent(json_encode($this->convertToCamelCase($content)));
            }
        }

        return $response;
    }

    private function convertToCamelCase($data)
    {
        if (is_array($data)) {
            $result = [];
            foreach ($data as $key => $value) {
                $camelKey = Str::camel($key);
                $result[$camelKey] = $this->convertToCamelCase($value);
            }
            return $result;
        }
        return $data;
    }
}
